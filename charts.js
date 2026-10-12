"use strict";
/* Gemensamma hjälpfunktioner och linjediagram för räntorna (ränteläget, bolån). */

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

/* Linjediagram med hovring: series = [{label, color, dash, points: [[datum, värde]]}]. */
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

