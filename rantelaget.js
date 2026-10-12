"use strict";

const REGIONS = {
  SE: { name: "Sverige", color: "var(--series-1)" },
  EU: { name: "Euroområdet", color: "var(--series-2)" },
  US: { name: "USA", color: "var(--series-3)" },
};
const CHARTS = {
  styr: { title: "Styrräntor", ids: ["se_policy", "eu_dfr", "us_fed_upper"], step: true },
  "2y": { title: "Statsobligationer 2 år", ids: ["se_gvb2y", "eu_y2y", "us_t2y"] },
  "10y": { title: "Statsobligationer 10 år", ids: ["se_gvb10y", "eu_y10y", "us_t10y"] },
};
const CURVE = {
  SE: ["se_swestr", "se_tb3m", "se_gvb2y", "se_gvb5y", "se_gvb10y"],
  EU: ["eu_estr", "eu_y3m", "eu_y2y", "eu_y5y", "eu_y10y"],
  US: ["us_effr", "us_t3m", "us_t2y", "us_t5y", "us_t10y", "us_t30y"],
};
const TENOR_LABEL = { 0: "Dag", 3: "3 mån", 24: "2 år", 60: "5 år", 120: "10 år", 360: "30 år" };
const TENORS = [0, 3, 24, 60, 120, 360];

const $ = (s) => document.querySelector(s);
const pct = (v, d = 2) => v == null ? "–" : v.toLocaleString("sv-SE", { minimumFractionDigits: d, maximumFractionDigits: d }) + " %";
const pp = (v) => v == null ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "±") + Math.abs(v).toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const dateSv = (d) => new Date(d + "T12:00:00").toLocaleDateString("sv-SE", { day: "numeric", month: "short", year: "numeric" });
const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.append(e);
  return e;
};

let S = null;

/** Senaste datum då serien bytte värde (för styrräntor: senaste beslutet). */
function lastChange(obs) {
  for (let i = obs.length - 1; i > 0; i--) {
    if (Math.abs(obs[i][1] - obs[i - 1][1]) > 1e-9) return { date: obs[i][0], from: obs[i - 1][1], to: obs[i][1] };
  }
  return null;
}

function arrow(v) {
  if (v == null || Math.abs(v) < 0.005) return "→";
  return v > 0 ? "↑" : "↓";
}

function sparkline(obs) {
  const cutoff = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);
  const pts = obs.filter(([d]) => d >= cutoff);
  const w = 56, h = 22, svg = el("svg", { viewBox: `0 0 ${w} ${h}`, width: w, height: h, class: "spark", "aria-hidden": "true" });
  if (pts.length < 2) return svg;
  const ys = pts.map((p) => p[1]), lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${(i / (pts.length - 1) * (w - 4) + 2).toFixed(1)},${(h - 3 - (p[1] - lo) / span * (h - 6)).toFixed(1)}`).join("");
  el("path", { d, class: "spark-line" }, svg);
  return svg;
}

function renderRegions() {
  const root = $("#regions");
  root.replaceChildren();
  for (const [code, reg] of Object.entries(REGIONS)) {
    const ids = Object.keys(S).filter((id) => S[id].region === code);
    const policy = ids.map((id) => S[id]).find((s) => s.group === "styr");
    const card = document.createElement("article");
    card.className = "region";
    const lc = policy ? lastChange(policy.obs) : null;
    card.innerHTML = `
      <h2><span class="swatch" style="background:${reg.color}"></span>${reg.name}</h2>
      ${policy ? `<div class="hero"><span class="hero-num">${pct(policy.latest.value)}</span>
        <span class="hero-label">${policy.name}</span>
        ${lc ? `<span class="hero-sub">Senast ändrad ${dateSv(lc.date)} (${pp(lc.to - lc.from)} procentenheter)</span>` : ""}</div>` : ""}
      <table class="rates">
        <thead><tr><th scope="col">Ränta</th><th scope="col" class="num">Nu</th><th scope="col" class="num">1 mån</th><th scope="col" class="num">1 år</th><th scope="col"><span class="sr">Trend senaste året</span></th></tr></thead>
        <tbody></tbody>
      </table>`;
    const tb = card.querySelector("tbody");
    for (const id of ids) {
      const s = S[id];
      if (s.group === "styr") continue;
      const tr = document.createElement("tr");
      tr.innerHTML = `<th scope="row">${s.name}${s.stale ? ' <span class="tag warn">ej uppdaterad</span>' : ""}</th>
        <td class="num">${pct(s.latest.value)}</td>
        <td class="num chg">${arrow(s.latest.chg_1m)} ${pp(s.latest.chg_1m)}</td>
        <td class="num chg">${arrow(s.latest.chg_1y)} ${pp(s.latest.chg_1y)}</td>
        <td class="sparkcell"></td>`;
      tr.title = `${s.name}: ${pct(s.latest.value)} per ${dateSv(s.latest.date)}`;
      const sp = sparkline(s.obs);
      sp.style.color = reg.color;
      tr.querySelector(".sparkcell").append(sp);
      tb.append(tr);
    }
    root.append(card);
  }
}

/* ---------- linjediagram med hovring ---------- */

function niceTicks(lo, hi, n = 5) {
  const span = hi - lo || 1, raw = span / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function legend(target, items) {
  target.replaceChildren(...items.map((it) => {
    const s = document.createElement("span");
    s.className = "key";
    s.innerHTML = `<svg width="22" height="10" aria-hidden="true"><line x1="1" y1="5" x2="21" y2="5" stroke="${it.color}" stroke-width="2.5" ${it.dash ? 'stroke-dasharray="4 3"' : ""} stroke-linecap="round"/></svg>${it.label}`;
    return s;
  }));
}

function lineChart(target, series, { step = false } = {}) {
  target.replaceChildren();
  const W = target.clientWidth || 800, H = Math.max(240, Math.min(360, W * 0.45));
  const m = { l: 44, r: 14, t: 12, b: 28 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img" }, target);
  const all = series.flatMap((s) => s.points);
  if (!all.length) return;
  const t = (d) => new Date(d + "T00:00:00Z").getTime();
  const x0 = Math.min(...all.map((p) => t(p[0]))), x1 = Math.max(...all.map((p) => t(p[0])));
  let y0 = Math.min(0, ...all.map((p) => p[1])), y1 = Math.max(...all.map((p) => p[1]));
  y1 += (y1 - y0) * 0.06;
  const X = (d) => m.l + (t(d) - x0) / (x1 - x0 || 1) * (W - m.l - m.r);
  const Y = (v) => H - m.b - (v - y0) / (y1 - y0 || 1) * (H - m.t - m.b);
  const g = el("g", { class: "grid" }, svg);
  for (const v of niceTicks(y0, y1)) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: v === 0 ? "zero" : "" }, g);
    el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", class: "axis" }, g).textContent = v.toLocaleString("sv-SE") + " %";
  }
  const years = new Date(x1).getUTCFullYear() - new Date(x0).getUTCFullYear();
  const startY = new Date(x0).getUTCFullYear();
  for (let y = startY; y <= new Date(x1).getUTCFullYear(); y++) {
    for (const mo of years <= 1 ? [0, 3, 6, 9] : years <= 3 ? [0, 6] : [0]) {
      const d = `${y}-${String(mo + 1).padStart(2, "0")}-01`;
      if (t(d) < x0 || t(d) > x1) continue;
      el("line", { x1: X(d), x2: X(d), y1: H - m.b, y2: H - m.b + 4, class: "tick" }, g);
      el("text", { x: X(d), y: H - 8, "text-anchor": "middle", class: "axis" }, g).textContent =
        mo === 0 ? String(y) : new Date(d).toLocaleDateString("sv-SE", { month: "short" });
    }
  }
  for (const s of series) {
    if (!s.points.length) continue;
    let d = "";
    s.points.forEach((p, i) => {
      const x = X(p[0]).toFixed(1), y = Y(p[1]).toFixed(1);
      if (!i) d += `M${x},${y}`;
      else d += step ? `H${x}V${y}` : `L${x},${y}`;
    });
    el("path", { d, class: "line", stroke: s.color, "stroke-dasharray": s.dash ? "5 4" : "none" }, svg);
  }
  // hovring: lodrät linje + värden för alla serier på närmaste datum
  const hover = el("g", { class: "hover", visibility: "hidden" }, svg);
  const vline = el("line", { y1: m.t, y2: H - m.b, class: "crosshair" }, hover);
  const dots = series.map((s) => el("circle", { r: 4.5, fill: s.color, class: "dot" }, hover));
  const tip = $("#tip");
  const at = (pts, d) => { let v = null; for (const p of pts) { if (p[0] <= d) v = p[1]; else break; } return v; };
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * (W / r.width);
    if (px < m.l || px > W - m.r) return leave();
    const time = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
    const d = new Date(time).toISOString().slice(0, 10);
    hover.setAttribute("visibility", "visible");
    vline.setAttribute("x1", px); vline.setAttribute("x2", px);
    const rows = series.map((s, i) => {
      const v = at(s.points, d);
      if (v == null) { dots[i].setAttribute("visibility", "hidden"); return ""; }
      dots[i].setAttribute("visibility", "visible");
      dots[i].setAttribute("cx", px); dots[i].setAttribute("cy", Y(v));
      return `<div class="tip-row"><svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="${s.color}"/></svg>${s.label}<b>${pct(v)}</b></div>`;
    }).join("");
    tip.innerHTML = `<div class="tip-date">${dateSv(d)}</div>${rows}`;
    tip.hidden = false;
    const tx = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = tx + "px";
    tip.style.top = (ev.clientY + 14 + window.scrollY) + "px";
  };
  const leave = () => { hover.setAttribute("visibility", "hidden"); tip.hidden = true; };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerleave", leave);
}

function renderChart() {
  const key = document.querySelector('input[name="chart"]:checked').value;
  const years = +document.querySelector('input[name="range"]:checked').value;
  const cfg = CHARTS[key];
  const cutoff = new Date(Date.now() - years * 365.25 * 864e5).toISOString().slice(0, 10);
  const series = cfg.ids.filter((id) => S[id]).map((id) => ({
    label: `${REGIONS[S[id].region].name} – ${S[id].name}`,
    color: REGIONS[S[id].region].color,
    points: S[id].obs.filter(([d]) => d >= cutoff),
  }));
  $("#chart-title").textContent = cfg.title;
  legend($("#legend"), series);
  lineChart($("#chart"), series, { step: cfg.step });
}

/* ---------- avkastningskurvor ---------- */

function renderCurve() {
  const target = $("#curve");
  target.replaceChildren();
  const W = target.clientWidth || 800, H = Math.max(220, Math.min(320, W * 0.4));
  const m = { l: 44, r: 14, t: 12, b: 28 };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, role: "img" }, target);
  const X = (ten) => m.l + TENORS.indexOf(ten) / (TENORS.length - 1) * (W - m.l - m.r);
  const lines = [];
  for (const [code, ids] of Object.entries(CURVE)) {
    for (const ago of [0, 365]) {
      const pts = [];
      for (const id of ids) {
        const s = S[id];
        if (!s || s.tenor_months == null) continue;
        let v = s.latest.value;
        if (ago) {
          const ref = new Date(new Date(s.latest.date).getTime() - ago * 864e5).toISOString().slice(0, 10);
          v = null;
          for (const p of s.obs) { if (p[0] <= ref) v = p[1]; else break; }
        }
        if (v != null) pts.push([s.tenor_months, v, s.name]);
      }
      lines.push({ code, ago, pts, color: REGIONS[code].color, dash: !!ago,
                   label: `${REGIONS[code].name} ${ago ? "för ett år sedan" : "nu"}` });
    }
  }
  const vals = lines.flatMap((l) => l.pts.map((p) => p[1]));
  const y0 = Math.min(0, ...vals), y1 = Math.max(...vals) * 1.08;
  const Y = (v) => H - m.b - (v - y0) / (y1 - y0) * (H - m.t - m.b);
  const g = el("g", { class: "grid" }, svg);
  for (const v of niceTicks(y0, y1)) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v), class: v === 0 ? "zero" : "" }, g);
    el("text", { x: m.l - 6, y: Y(v) + 4, "text-anchor": "end", class: "axis" }, g).textContent = v.toLocaleString("sv-SE") + " %";
  }
  for (const ten of TENORS) {
    el("text", { x: X(ten), y: H - 8, "text-anchor": "middle", class: "axis" }, g).textContent = TENOR_LABEL[ten];
  }
  const tip = $("#tip");
  for (const l of lines) {
    if (l.pts.length < 2) continue;
    el("path", { d: l.pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(""),
                 class: "line", stroke: l.color, "stroke-dasharray": l.dash ? "5 4" : "none" }, svg);
    for (const p of l.pts) {
      const c = el("circle", { cx: X(p[0]), cy: Y(p[1]), r: l.dash ? 3.5 : 4.5, fill: l.dash ? "var(--bg)" : l.color,
                               stroke: l.color, "stroke-width": 2, class: "dot" }, svg);
      const hit = el("circle", { cx: X(p[0]), cy: Y(p[1]), r: 12, class: "hit" }, svg);
      hit.addEventListener("pointerenter", (ev) => {
        c.setAttribute("r", 6);
        tip.innerHTML = `<div class="tip-date">${l.label}</div><div class="tip-row">${p[2]}<b>${pct(p[1])}</b></div>`;
        tip.hidden = false;
        tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - 220) + "px";
        tip.style.top = (ev.clientY + 14 + window.scrollY) + "px";
      });
      hit.addEventListener("pointerleave", () => { c.setAttribute("r", l.dash ? 3.5 : 4.5); tip.hidden = true; });
    }
  }
  legend($("#curve-legend"), lines.filter((l) => l.pts.length > 1));
}

function renderSources() {
  const src = {};
  for (const s of Object.values(S)) src[s.source] = s.source_url;
  $("#sources").innerHTML = "Källor: " + Object.entries(src).map(([n, u]) => `<a href="${u}" rel="noopener" target="_blank">${n}</a>`).join(", ") +
    ". Styrränta för euroområdet är ECB:s inlåningsränta och för USA den övre gränsen i Feds målintervall. Statspapper i euroområdet avser AAA-värderade stater.";
}

let resizeTimer;
fetch("data/macro.json", { cache: "no-cache" })
  .then((r) => r.json())
  .then((d) => {
    S = d.series;
    $("#updated").textContent = `Data uppdaterad ${new Date(d.generated_at).toLocaleString("sv-SE", { dateStyle: "long", timeStyle: "short" })}.`;
    renderRegions();
    renderChart();
    renderCurve();
    renderSources();
    document.querySelectorAll('input[name="chart"], input[name="range"]').forEach((i) => i.addEventListener("change", renderChart));
    addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { renderChart(); renderCurve(); }, 150); });
  })
  .catch(() => { $("#regions").textContent = "Kunde inte läsa in räntorna."; });
