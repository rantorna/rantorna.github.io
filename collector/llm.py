"""Tunt lager mot Claude med strukturerat JSON-svar.

Två vägar, i den här ordningen:
  - ANTHROPIC_API_KEY  -> Anthropic SDK (Messages API, output_config.format)
  - CLAUDE_CODE_OAUTH_TOKEN eller inloggad `claude` -> `claude -p --json-schema`
    (använder en Claude-prenumeration, t.ex. via `claude setup-token` i Actions)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

def model() -> str:
    """Segmentets egen modell om den finns, annars RANTORNA_MODEL. Läses vid varje anrop,
    så att .env (som laddas efter import) får effekt."""
    from . import segments
    return segments.cur().model or os.environ.get("RANTORNA_MODEL", "claude-haiku-5-5")


def cheap_model() -> str:
    return os.environ.get("RANTORNA_CHEAP_MODEL", "claude-haiku-5-5")

usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


class LLMError(RuntimeError):
    pass


class LimitReached(LLMError):
    """Användnings-/sessionsgräns nådd – inga fler anrop i den här körningen."""


limit_hit = False
_LIMIT = ("session limit", "usage limit", "weekly limit", "hit your", "rate limit", "rate_limit", "429", "overloaded")


def _check_limit(text: str):
    global limit_hit
    if any(k in text.lower() for k in _LIMIT):
        limit_hit = True
        raise LimitReached(text[:200])


def backend() -> str | None:
    forced = os.environ.get("RANTORNA_LLM")
    if forced:
        return None if forced == "none" else forced
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") and shutil.which(_bin()):
        return "cli"
    return None


def _bin() -> str:
    return os.environ.get("CLAUDE_BIN", "claude")


def available() -> bool:
    return backend() is not None


def json_call(task: str, system: str, user: str, schema: dict, cheap: bool = False,
              max_tokens: int = 32000) -> dict:
    model = cheap_model() if cheap else globals()["model"]()
    if limit_hit:
        raise LimitReached("gränsen redan nådd i den här körningen")
    b = backend()
    usage["calls"] += 1
    if b == "api":
        return _api(model, system, user, schema, max_tokens, effort="low" if cheap else "medium")
    if b == "cli":
        return _cli(model, system, user, schema)
    raise LLMError("Ingen LLM konfigurerad (sätt ANTHROPIC_API_KEY eller CLAUDE_CODE_OAUTH_TOKEN)")


def _api(model, system, user, schema, max_tokens, effort):
    import anthropic

    client = anthropic.Anthropic()
    try:
        return _api_inner(client, model, system, user, schema, max_tokens, effort)
    except anthropic.RateLimitError as e:
        _check_limit(f"rate limit {e}")
        raise


ANSWER_TOOL = "lamna_svar"
ANSWER_RULE = (f"\n\nLämna alltid resultatet genom att anropa verktyget {ANSWER_TOOL} exakt en gång, "
               "med hela svaret som indata. Skriv ingen annan text.")


def _answer_tool(schema: dict) -> dict:
    # Svar via verktygsanrop i stället för output_config.format: strukturerade utdata tillåter
    # högst 16 fält som kan vara null, och tolkningsschemat har betydligt fler.
    return {"name": ANSWER_TOOL, "description": "Lämna det strukturerade svaret.", "input_schema": schema}


def _answer(msg) -> dict:
    """Svaret ur verktygsanropet (eller, i nödfall, ur JSON i texten)."""
    for b in msg.content:
        if b.type == "tool_use" and b.name == ANSWER_TOOL:
            return b.input
    text = next((b.text for b in reversed(msg.content) if b.type == "text"), None)
    if text:
        t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        return json.loads(t)
    raise LLMError("inget svar")


def _api_inner(client, model, system, user, schema, max_tokens, effort):
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system + ANSWER_RULE, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        tools=[_answer_tool(schema)],
        output_config={"effort": effort},
    ) as stream:
        msg = stream.get_final_message()
    usage["input_tokens"] += msg.usage.input_tokens
    usage["output_tokens"] += msg.usage.output_tokens
    if msg.stop_reason == "refusal":
        raise LLMError("modellen avböjde")
    if msg.stop_reason == "max_tokens":
        raise LLMError("svaret blev för långt (max_tokens)")
    return _answer(msg)


def _cli(model, system, user, schema, tools: str = ""):
    cmd = [
        _bin(), "-p", "--output-format", "json", "--model", model, "--tools", tools,
        "--json-schema", json.dumps(schema), "--append-system-prompt", system,
    ]
    if tools:
        cmd += ["--allowedTools", tools.replace(",", " ")]
    r = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=900)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        _check_limit(r.stderr + r.stdout)
        raise LLMError(f"claude -p: {r.stderr[:300] or r.stdout[:300]}")
    if out.get("is_error"):
        _check_limit(str(out.get("result", "")))
        raise LLMError(f"claude -p: {out.get('result', '')[:300]}")
    u = out.get("usage", {})
    usage["input_tokens"] += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    usage["output_tokens"] += u.get("output_tokens", 0)
    data = out.get("structured_output")
    if data is None:
        data = json.loads(out.get("result", "null"))
    return data


def research_call(system: str, user: str, schema: dict) -> dict:
    """Som json_call men med webbsökning och webbhämtning tillgängliga."""
    model = os.environ.get("RANTORNA_RESEARCH_MODEL") or globals()["model"]()
    if limit_hit:
        raise LimitReached("gränsen redan nådd i den här körningen")
    b = backend()
    usage["calls"] += 1
    if b == "cli":
        return _cli(model, system, user, schema, tools="WebSearch,WebFetch")
    if b == "api":
        return _api_research(model, system, user, schema)
    raise LLMError("Ingen LLM konfigurerad")


def _web_tools(model: str) -> list[dict]:
    """Webbverktygen med dynamisk filtrering (2026-02-09) finns på Sonnet/Opus; Haiku har grundvarianterna."""
    s, f = ("web_search_20250305", "web_fetch_20250910") if "haiku" in model else ("web_search_20260209", "web_fetch_20260209")
    return [{"type": s, "name": "web_search", "max_uses": 8}, {"type": f, "name": "web_fetch", "max_uses": 8}]


def _api_research(model, system, user, schema):
    import anthropic

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": user}]
    for _ in range(6):  # pause_turn: servern vill fortsätta en lång sökslinga
        with client.messages.stream(
            model=model,
            max_tokens=16000,
            system=system + ANSWER_RULE,
            messages=messages,
            tools=_web_tools(model) + [_answer_tool(schema)],
            output_config={"effort": "medium"},
        ) as stream:
            msg = stream.get_final_message()
        usage["input_tokens"] += msg.usage.input_tokens
        usage["output_tokens"] += msg.usage.output_tokens
        if msg.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": msg.content})
            continue
        if msg.stop_reason == "refusal":
            raise LLMError("modellen avböjde")
        return _answer(msg)
    raise LLMError("för många pause_turn")
