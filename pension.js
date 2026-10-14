"use strict";

const DETAIL = {
  rate_kind: "Hur räntan sätts",
  rate_basis: "Före/efter avgifter och skatt",
  monthly_rate_percent: "Senaste månaden",
  return_period: "Avkastningsperiod",
  guaranteed_rate_percent: "Garantiränta",
  fee_terms: "Avgifter",
  fee_fixed_sek: "Fast avgift",
  equity_share_percent: "Andel aktier",
  available_to: "Vem kan teckna",
  product_kind: "Gäller",
};
const PCT_FIELDS = new Set(["monthly_rate_percent", "guaranteed_rate_percent", "equity_share_percent"]);

let P = null;
const val = (p, k) => (p.fields[k] || {}).value ?? null;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const monthSv = (ym) => ym ? new Date(ym.slice(0, 7) + "-15").toLocaleDateString("sv-SE", { month: "short", year: "numeric" }) : "";

/** Uppgift äldre än sex månader – visas, men markeras. */
function stale(ym) {
  if (!ym || !/^\d{4}-\d{2}/.test(ym)) return false;
  return (Date.now() - new Date(ym.slice(0, 7) + "-15").getTime()) / 864e5 > 190;
}

function quote(b, f) {
  if (!f || !f.quote || f.value == null) return "";
  const src = b.sources[f.source];
  return `<q>${esc(f.quote)}</q>${src ? ` <a href="${src.url}" rel="noopener nofollow" target="_blank">källa</a>` : ""}`;
}

function cell(b, p, k) {
  const v = val(p, k);
  if (v == null) return `<td class="num muted">–</td>`;
  return `<td class="num" title="${esc(p.fields[k].quote || "")}">${k === "consolidation_percent" ? Math.round(v) + " %" : pct(v, k === "fee_capital_percent" ? 2 : 1)}</td>`;
}

function detail(b, p) {
  const rows = Object.entries(DETAIL).map(([k, label]) => {
    const f = p.fields[k];
    if (!f || f.value == null) return "";
    let v = f.value;
    if (PCT_FIELDS.has(k)) v = pct(v);
    else if (k === "fee_fixed_sek") v = `${v} kr/år`;
    return `<dt>${label}</dt><dd>${esc(v)} ${quote(b, f)}</dd>`;
  }).join("");
  const main = ["rate_percent", "return_1y_percent", "return_5y_avg_percent", "consolidation_percent", "fee_capital_percent"]
    .map((k) => p.fields[k]?.value != null ? `<dt>${{ rate_percent: "Ränta", return_1y_percent: "Avkastning 1 år", return_5y_avg_percent: "Snitt 5 år", consolidation_percent: "Konsolidering", fee_capital_percent: "Avgift" }[k]}</dt><dd>${quote(b, p.fields[k])}</dd>` : "").join("");
  return `<dl class="terms">${main}${rows}</dl>
    <p class="sources">${b.bank.legal_name && b.bank.legal_name !== b.bank.name ? esc(b.bank.legal_name) + ". " : ""}Senast kontrollerat ${new Date(b.checked_at).toLocaleDateString("sv-SE")}. <a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">Till bolaget</a></p>`;
}

function hasFigures(p) {
  return ["rate_percent", "return_1y_percent", "consolidation_percent"].some((k) => val(p, k) != null);
}

function render() {
  const kind = $("#kind").value, sortKey = $("#sort").value;
  const asc = sortKey === "fee_capital_percent";
  const items = [];
  for (const b of P.banks) for (const p of b.products || []) {
    if (!hasFigures(p)) continue;
    const k = val(p, "product_kind");
    if (kind && k !== kind && k !== "flera") continue;
    items.push({ b, p });
  }
  items.sort((x, y) => {
    const a = val(x.p, sortKey), c = val(y.p, sortKey);
    if (a == null && c == null) return x.b.bank.name.localeCompare(y.b.bank.name, "sv");
    if (a == null) return 1;
    if (c == null) return -1;
    return asc ? a - c : c - a;
  });
  const tb = $("#pen tbody");
  tb.replaceChildren();
  for (const { b, p } of items) {
    const tr = document.createElement("tr");
    tr.className = "mtg-row";
    const r = val(p, "rate_percent"), ym = val(p, "rate_month");
    const kindTag = val(p, "rate_kind") === "månadsvis avkastningsränta" ? ' <span class="tag note">månadsvis</span>' : "";
    const staleTag = r != null && stale(ym) ? ` <span class="tag part" title="Räntan avser ${monthSv(ym)}">äldre uppgift</span>` : "";
    const status = p.status !== "verifierad" ? ` <span class="tag part" title="${p.status}">?</span>` : "";
    tr.innerHTML = `<th scope="row"><button class="expand" aria-expanded="false">${esc(b.bank.name)}</button><br><span class="muted">${esc(p.name)}</span></th>
      <td class="num">${r == null ? '<span class="muted">–</span>' : `<b>${pct(r, 1)}</b>`}${kindTag}${staleTag}${status}${ym && r != null ? `<br><span class="muted small">${monthSv(ym)}</span>` : ""}</td>
      ${cell(b, p, "return_1y_percent")}${cell(b, p, "return_5y_avg_percent")}${cell(b, p, "consolidation_percent")}${cell(b, p, "fee_capital_percent")}`;
    const det = document.createElement("tr");
    det.className = "mtg-detail";
    det.hidden = true;
    tr.querySelector(".expand").addEventListener("click", (e) => {
      if (!det.firstChild) det.innerHTML = `<td colspan="6">${detail(b, p)}</td>`;
      det.hidden = !det.hidden;
      e.currentTarget.setAttribute("aria-expanded", String(!det.hidden));
    });
    tb.append(tr, det);
  }
  $("#pen-note").textContent = `${items.length} förvaltningar. Räntan är den återbäringsränta bolaget anger (för "månadsvis": senaste tolv månaderna). – = bolaget anger inte siffran eller den gick inte att belägga. ? = inte helt verifierad.`;
}

function renderMissing() {
  const miss = P.banks.filter((b) => !(b.products || []).some(hasFigures));
  const el = $("#missing");
  el.hidden = !miss.length;
  el.querySelector("summary").textContent = `${miss.length} bolag kunde inte läsas automatiskt`;
  el.querySelector("ul").innerHTML = miss.map((b) => `<li><a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">${esc(b.bank.name)}</a></li>`).join("");
}

fetch("data/pension.json", { cache: "no-cache" }).then((r) => r.json()).then((d) => {
  P = d;
  const q = new URLSearchParams(location.search).get("typ");
  if (q) $("#kind").value = q;
  render();
  renderMissing();
  $("#updated").textContent = `Data uppdaterad ${new Date(d.generated_at).toLocaleString("sv-SE", { dateStyle: "long", timeStyle: "short" })}.`;
  $("#kind").addEventListener("change", render);
  $("#sort").addEventListener("change", render);
});
