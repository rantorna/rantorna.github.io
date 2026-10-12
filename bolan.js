"use strict";

const BINDINGS = [[3, "3 mån"], [12, "1 år"], [24, "2 år"], [36, "3 år"], [60, "5 år"], [120, "10 år"]];
// SCB-serier per bindningstid (SCB grupperar: 3 mån–1 år, 1–2 år osv.)
const SCB_LINES = [
  ["se_mtg_new_var", "Rörlig (≤ 3 mån)", "var(--series-1)"],
  ["se_mtg_new_1y2y", "1–2 år", "var(--series-2)"],
  ["se_mtg_new_3y5y", "3–5 år", "var(--series-3)"],
  ["se_mtg_new_5y", "Över 5 år", "var(--series-4)"],
];
const DETAIL = {
  ltv_pricing: "Belåningsgrad",
  discounts: "Rabatter",
  requires_other_products: "Kräver annan kundrelation",
  max_ltv_percent: "Högsta belåningsgrad",
  eligibility: "Vem kan låna",
};

let M = null, B = null;
const val = (p, k) => (p.fields[k] || {}).value ?? null;
const monthSv = (ym) => ym ? new Date(ym.slice(0, 7) + "-15").toLocaleDateString("sv-SE", { month: "long", year: "numeric" }) : "";

function renderMarket() {
  const root = $("#market");
  const card = (title, s, extra = "") => {
    if (!s) return "";
    const l = s.latest;
    return `<article class="region">
      <h2>${title}</h2>
      <div class="hero"><span class="hero-num">${pct(l.value)}</span>
        <span class="hero-label">${s.name}${s.group === "bolån" ? ", " + monthSv(l.date) : ""}</span>
        <span class="hero-sub">${l.chg_1m != null ? `${pp(l.chg_1m)} sedan månaden innan · ` : ""}${pp(l.chg_1y)} på ett år${extra}</span></div>
    </article>`;
  };
  root.innerHTML =
    card("Rörligt bolån", M.se_mtg_new_var) +
    card("Bundet 3–5 år", M.se_mtg_new_3y5y) +
    card("Styrräntan", M.se_policy, ` · <a href="rantelaget.html">Ränteläget</a>`);
}

function productFor(bank, months) {
  return (bank.products || []).find((p) => val(p, "binding_months") === months && val(p, "rate_percent") != null
    || val(p, "binding_months") === months && val(p, "avg_rate_percent") != null);
}

function category(b) {
  const cats = (b.products || []).map((p) => val(p, "loan_category")).filter(Boolean);
  return cats.find((c) => c !== "vanligt bolån") || cats[0] || null;
}

function hasRates(b) {
  return (b.products || []).some((p) => val(p, "rate_percent") != null || val(p, "avg_rate_percent") != null);
}

function rows() {
  const special = $("#special").checked;
  return B.banks.filter((b) => hasRates(b) && (special || !["specialistbolån", "seniorlån"].includes(category(b))));
}

function renderTable() {
  const kind = document.querySelector('input[name="kind"]:checked').value;
  const key = kind === "avg" ? "avg_rate_percent" : "rate_percent";
  const sortM = +$("#sort").value;
  const head = `<tr><th scope="col">Långivare</th>${BINDINGS.map(([, l]) => `<th scope="col" class="num">${l}</th>`).join("")}</tr>`;
  $("#mtg thead").innerHTML = head;
  // lägsta ränta per kolumn markeras (fet stil + markör, inte bara färg)
  const best = {};
  for (const [m] of BINDINGS) {
    const vals = rows().map((b) => productFor(b, m)).filter(Boolean).map((p) => val(p, key)).filter((v) => v != null);
    best[m] = vals.length ? Math.min(...vals) : null;
  }
  const sorted = rows().sort((a, b) => {
    const va = val(productFor(a, sortM) || { fields: {} }, key), vb = val(productFor(b, sortM) || { fields: {} }, key);
    if (va == null && vb == null) return a.bank.name.localeCompare(b.bank.name, "sv");
    if (va == null) return 1;
    if (vb == null) return -1;
    return va - vb;
  });
  const tb = $("#mtg tbody");
  tb.replaceChildren();
  for (const b of sorted) {
    const tr = document.createElement("tr");
    tr.className = "mtg-row";
    const cat = category(b);
    const catTag = cat && cat !== "vanligt bolån" ? ` <span class="tag note">${cat}</span>` : "";
    tr.innerHTML = `<th scope="row"><button class="expand" aria-expanded="false">${b.bank.name}</button>${catTag}</th>` +
      BINDINGS.map(([m]) => {
        const p = productFor(b, m);
        const v = p ? val(p, key) : null;
        if (v == null) return `<td class="num muted">–</td>`;
        const isBest = best[m] != null && Math.abs(v - best[m]) < 1e-9;
        const status = p.status !== "verifierad" ? ` <span class="tag part" title="${p.status}">?</span>` : "";
        return `<td class="num${isBest ? " best" : ""}">${isBest ? '<span class="sr">Lägst: </span>▼ ' : ""}${pct(v)}${status}</td>`;
      }).join("");
    const det = document.createElement("tr");
    det.className = "mtg-detail";
    det.hidden = true;
    det.innerHTML = `<td colspan="${BINDINGS.length + 1}">${detail(b)}</td>`;
    tr.querySelector(".expand").addEventListener("click", (e) => {
      det.hidden = !det.hidden;
      e.currentTarget.setAttribute("aria-expanded", String(!det.hidden));
    });
    tb.append(tr, det);
  }
  const months = new Set();
  for (const b of rows()) for (const p of b.products) if (val(p, "avg_rate_month")) months.add(val(p, "avg_rate_month"));
  $("#mtg-note").textContent = kind === "avg"
    ? `Snitträntor avser senast redovisade månad (${[...months].sort().slice(-1).map(monthSv)[0] || "–"} för de flesta). ▼ = lägst i kolumnen. ? = inte helt verifierad.`
    : "Listräntor enligt långivarnas sidor i dag. ▼ = lägst i kolumnen. ? = inte helt verifierad. Klicka på en långivare för villkor och källor.";
}

function quote(b, f) {
  if (!f || !f.quote || f.value == null) return "";
  const src = b.sources[f.source];
  return `<q>${escapeHtml(f.quote)}</q>${src ? ` <a href="${src.url}" rel="noopener nofollow" target="_blank">källa</a>` : ""}`;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function detail(b) {
  const lines = BINDINGS.map(([m, l]) => {
    const p = productFor(b, m);
    if (!p) return "";
    const lr = p.fields.rate_percent, ar = p.fields.avg_rate_percent;
    const diff = lr?.value != null && ar?.value != null ? ` · snitt minus lista: ${pp(ar.value - lr.value)} procentenheter` : "";
    return `<dt>${l}</dt><dd>Lista ${pct(lr?.value)} · snitt ${pct(ar?.value)}${val(p, "avg_rate_month") ? ` (${monthSv(val(p, "avg_rate_month"))})` : ""}${diff}
      ${quote(b, lr)} ${quote(b, ar)}</dd>`;
  }).join("");
  const first = (b.products || [])[0];
  const terms = first ? Object.entries(DETAIL).map(([k, label]) => {
    const f = first.fields[k];
    if (!f || f.value == null) return "";
    const v = typeof f.value === "boolean" ? (f.value ? "Ja" : "Nej") : k === "max_ltv_percent" ? f.value + " %" : escapeHtml(String(f.value));
    return `<dt>${label}</dt><dd>${v} ${quote(b, f)}</dd>`;
  }).join("") : "";
  return `<dl class="terms">${lines}${terms}</dl>
    <p class="sources">${b.bank.legal_name && b.bank.legal_name !== b.bank.name ? escapeHtml(b.bank.legal_name) + ". " : ""}Senast kontrollerat ${new Date(b.checked_at).toLocaleDateString("sv-SE")}. <a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">Till långivaren</a></p>`;
}

function renderMissing() {
  const miss = B.banks.filter((b) => !hasRates(b));
  const el = $("#missing");
  el.hidden = !miss.length;
  el.querySelector("summary").textContent = `${miss.length} långivare kunde inte läsas automatiskt`;
  el.querySelector("ul").innerHTML = miss.sort((a, b) => a.bank.name.localeCompare(b.bank.name, "sv"))
    .map((b) => `<li><a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">${escapeHtml(b.bank.name)}</a></li>`).join("");
}

function renderChart() {
  const years = +document.querySelector('input[name="range"]:checked').value;
  const cutoff = new Date(Date.now() - years * 365.25 * 864e5).toISOString().slice(0, 10);
  const series = SCB_LINES.filter(([id]) => M[id]).map(([id, label, color]) => ({
    label, color, points: M[id].obs.filter(([d]) => d >= cutoff),
  }));
  if (M.se_policy) series.push({ label: "Styrräntan", color: "var(--muted)", dash: true,
                                 points: M.se_policy.obs.filter(([d]) => d >= cutoff) });
  legend($("#legend"), series);
  lineChart($("#chart"), series);
}

let resizeTimer;
Promise.all([
  fetch("data/macro.json", { cache: "no-cache" }).then((r) => r.json()),
  fetch("data/mortgage.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : { banks: [] }).catch(() => ({ banks: [] })),
]).then(([macro, mtg]) => {
  M = macro.series;
  B = mtg;
  $("#sort").innerHTML = BINDINGS.map(([m, l]) => `<option value="${m}"${m === 3 ? " selected" : ""}>${l}</option>`).join("");
  renderMarket();
  renderTable();
  renderMissing();
  renderChart();
  $("#updated").textContent = `Data uppdaterad ${new Date(mtg.generated_at || macro.generated_at).toLocaleString("sv-SE", { dateStyle: "long", timeStyle: "short" })}.`;
  document.querySelectorAll('input[name="kind"]').forEach((i) => i.addEventListener("change", renderTable));
  $("#sort").addEventListener("change", renderTable);
  $("#special").addEventListener("change", renderTable);
  document.querySelectorAll('input[name="range"]').forEach((i) => i.addEventListener("change", renderChart));
  addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderChart, 150); });
});
