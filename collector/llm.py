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

MODEL = os.environ.get("RANTORNA_MODEL", "claude-opus-5-5")
CHEAP_MODEL = os.environ.get("RANTORNA_CHEAP_MODEL", "claude-haiku-5-5")

usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


class LLMError(RuntimeError):
    pass


def backend() -> str | None:
    forced = os.environ.get("RANTORNA_LLM")
    if forced:
        return None if forced == "none" else forced
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") and shutil.which("claude"):
        return "cli"
    return None


def available() -> bool:
    return backend() is not None


def json_call(task: str, system: str, user: str, schema: dict, cheap: bool = False,
              max_tokens: int = 32000) -> dict:
    model = CHEAP_MODEL if cheap else MODEL
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
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        msg = stream.get_final_message()
    usage["input_tokens"] += msg.usage.input_tokens
    usage["output_tokens"] += msg.usage.output_tokens
    if msg.stop_reason == "refusal":
        raise LLMError("modellen avböjde")
    if msg.stop_reason == "max_tokens":
        raise LLMError("svaret blev för långt (max_tokens)")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if text is None:
        raise LLMError("inget textsvar")
    return json.loads(text)


def _cli(model, system, user, schema):
    cmd = [
        "claude", "-p", "--output-format", "json", "--model", model, "--tools", "",
        "--json-schema", json.dumps(schema), "--append-system-prompt", system,
    ]
    r = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=900)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise LLMError(f"claude -p: {r.stderr[:300] or r.stdout[:300]}")
    if out.get("is_error"):
        raise LLMError(f"claude -p: {out.get('result', '')[:300]}")
    u = out.get("usage", {})
    usage["input_tokens"] += u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    usage["output_tokens"] += u.get("output_tokens", 0)
    data = out.get("structured_output")
    if data is None:
        data = json.loads(out.get("result", "null"))
    return data
