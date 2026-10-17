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
    const ids = Object.keys(S).filter((id) => S[id].region === code && !["bolån", "officiell", "inflation", "företag", "konsumtion", "inlåning"].includes(S[id].group));
    const policy = ids.map((id) => S[id]).find((s) => s.group === "styr");
    const card = document.createElement("article");
    card.className = "region";
    const lc = policy ? lastChange(policy.obs) : null;
    card.innerHTML = `
      <h2><span class="swatch" style="background:${reg.color}"></span>${reg.name}</h2>
      ${policy ? `<div class="hero"><span class="hero-num">${pct(policy.latest.value)}</span>
        <span class="hero-label">${policy.name}</span>
        ${lc ? `<span class="hero-sub">Senast ändrad ${dateSv(lc.date)} (${pp(lc.to - lc.from)} procentenheter)</span>` : ""}</div>` : ""}
      ${(() => {
        const dates = ids.map((id) => S[id]).filter((x) => x.group !== "styr").map((x) => x.latest.date).sort();
        return dates.length ? `<p class="asof">Marknadsräntor per ${dateSv(dates[dates.length - 1])}</p>` : "";
      })()}
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

/** Officiella räntor: statslåneränta (och ISK-skatten den styr), skattekonto, referens-/dröjsmålsränta, CSN, inflation. */
function renderOfficial() {
  const g = (id) => S[id]?.latest?.value ?? null;
  const since = (id) => {
    const s = S[id];
    if (!s) return "";
    const lc = lastChange(s.obs);
    return lc ? dateSv(lc.date) : dateSv(s.obs[0][0]);
  };
  const card = (title, big, label, lines, sparkId) => `<article class="region off-card">
      <h3>${title}</h3>
      <div class="hero"><span class="hero-num">${big}</span><span class="hero-label">${label}</span></div>
      ${sparkId ? '<div class="off-spark" data-id="' + sparkId + '"></div>' : ""}
      <ul class="off-lines">${lines.filter(Boolean).map((l) => `<li>${l}</li>`).join("")}</ul>
    </article>`;
  const slr = g("se_slr"), kpif = g("se_kpif"), pol = g("se_policy");
  const year = S.se_isk_schablon ? S.se_isk_schablon.latest.date.slice(0, 4) : "";
  const grund = g("se_isk_grund");
  // Nästa års ISK-skatt avgörs av statslåneräntan 30 november – en prognos om räntan står still.
  const nextSchablon = slr != null ? Math.max(1.25, slr + 1) : null;
  const cards = [
    S.se_slr && card("Statslåneräntan", pct(slr), `gäller från ${dateSv(S.se_slr.latest.date)}`, [
      `${pp(S.se_slr.latest.chg_1y)} procentenheter på ett år`,
      g("se_isk_schablon") != null ? `<b>ISK och kapitalförsäkring ${year}:</b> schablonränta ${pct(g("se_isk_schablon"))} – skatt ${pct(g("se_isk_skatt"), 3)} av kapitalet${grund ? ` över ${kr0(grund)} kr` : ""}` : "",
      nextSchablon != null ? `Om räntan står kvar till 30 november blir skatten ${+year + 1} ca ${pct(nextSchablon * 0.3, 2)} (schablon ${pct(nextSchablon)})` : "",
      "Används också för periodiseringsfonder och räntefördelning.",
    ], "se_slr"),
    S.se_skv_intakt && card("Skattekontot", pct(g("se_skv_intakt"), 3), "intäktsränta, skattefri", [
      `Kostnadsränta ${pct(g("se_skv_kost_lag"), 1)} (låg) och ${pct(g("se_skv_kost_hog"), 1)} (hög)`,
      `Basränta ${pct(g("se_skv_bas"), 1)}, gäller från ${since("se_skv_bas")}`,
      "Intäktsräntan är skattefri – motsvarar ca " + pct(g("se_skv_intakt") / 0.7, 2) + " på ett vanligt sparkonto före skatt.",
    ]),
    S.se_ref && card("Referensränta", pct(g("se_ref")), `från ${since("se_ref")}`, [
      S.se_drojsmal ? `<b>Dröjsmålsränta ${pct(g("se_drojsmal"))}</b> – referensräntan + 8 procentenheter (räntelagen)` : "",
      "Fastställs av Riksbanken varje halvår.",
    ]),
    S.se_csn && card("CSN studielån", pct(g("se_csn"), 3), `räntan ${S.se_csn.latest.date.slice(0, 4)}`, [
      S.se_csn_aterkrav ? `Ränta på återkrav ${pct(g("se_csn_aterkrav"))}` : "",
      "Rörlig, fastställs av regeringen inför varje år. Inte avdragsgill.",
    ]),
    S.se_kpif && card("Inflation (KPIF)", pct(kpif, 1), `12 månader till ${new Date(S.se_kpif.latest.date).toLocaleDateString("sv-SE", { month: "long", year: "numeric" })}`, [
      pol != null ? `Real styrränta ${pp(pol - kpif)} procentenheter` : "",
      slr != null ? `Real statslåneränta ${pp(slr - kpif)} procentenheter` : "",
      `På <a href="./">Sparkonton</a> kan du se räntan efter skatt och inflation.`,
    ], "se_kpif"),
  ].filter(Boolean);
  $("#official").innerHTML = cards.join("");
  document.querySelectorAll(".off-spark").forEach((d) => {
    const sp = sparkline(S[d.dataset.id].obs);
    sp.style.color = "var(--series-1)";
    d.append(sp);
  });
}

const kr0 = (v) => Math.round(v).toLocaleString("sv-SE");

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
    renderOfficial();
    renderChart();
    renderCurve();
    renderSources();
    renderForecast($("#forecast"), d);
    document.querySelectorAll('input[name="chart"], input[name="range"]').forEach((i) => i.addEventListener("change", renderChart));
    addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { renderChart(); renderCurve(); }, 150); });
  })
  .catch(() => { $("#regions").textContent = "Kunde inte läsa in räntorna."; });
