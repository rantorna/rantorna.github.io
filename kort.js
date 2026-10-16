"use strict";
// Kreditkort. Använder hjälpfunktionerna i lan.js (val, esc, kr, quote).

const C_DETAIL = {
  card_type: "Typ", network: "Nätverk", annual_fee_sek: "Årsavgift", monthly_fee_sek: "Kortavgift per månad",
  invoice_fee_sek: "Aviavgift", rate_percent: "Ränta", rate_max_percent: "Högsta ränta", interest_free_days: "Räntefria dagar",
  credit_limit_max_sek: "Högsta kredit", currency_fee_percent: "Valutapåslag", atm_fee_percent: "Kontantuttag",
  atm_fee_min_sek: "Kontantuttag, lägst", example_effective_rate_percent: "Representativt exempel",
  travel_insurance: "Reseförsäkring", bonus: "Bonus", requires_other_products: "Kräver kundrelation",
  min_age: "Lägsta ålder", min_income_sek: "Lägsta inkomst", requirements: "Krav",
};
const C_PCT = new Set(["rate_percent", "rate_max_percent", "currency_fee_percent", "atm_fee_percent", "example_effective_rate_percent"]);
const C_KR = new Set(["annual_fee_sek", "monthly_fee_sek", "invoice_fee_sek", "credit_limit_max_sek", "atm_fee_min_sek", "min_income_sek"]);

let K = null;

/** Uppslaget ger ibland en produktbeskrivning som varumärke ("Betal- och kreditkort Mastercard
 *  (Sparbanken X)"). Visa då bolagets namn i stället. */
function issuer(b) {
  // Kortets namn står i produktraden; här räcker utgivaren ("SAS EuroBonus Mastercard" -> "SAS EuroBonus").
  const short = b.bank.name.replace(/\s*[(–].*$/, "").replace(/,.*$/, "").replace(/\s+(betal|kreditkort|mastercard|visa|kort)\b.*$/i, "").trim();
  // Står bara korttypen kvar ("Betal- och kreditkort Mastercard"), är bolagsnamnet bättre.
  if (short && !/^(betal|visa|mastercard|kreditkort)/i.test(short) && !/sparbank/i.test(b.bank.legal_name || "")) return short;
  const legal = (b.bank.legal_name || "").replace(/,.*$/, "").replace(/\s*\(publ\)/i, "").replace(/\s+(AB|Aktiebolag)$/i, "").trim();
  return legal || short || b.bank.name;
}
const num = (sel) => parseInt(($(sel).value || "").replace(/\D/g, ""), 10) || 0;

/** Kortavgift per månad som inte bara är årsavgiften uttryckt per månad ("2 100 kr/år, 175 kr/mån"). */
function extraMonthly(p) {
  const a = val(p, "annual_fee_sek"), m = val(p, "monthly_fee_sek");
  if (m == null || !m || a == null) return null;   // utan årsavgift räknas månadsavgiften separat
  return a != null && a > 0 && Math.abs(m * 12 - a) / a <= 0.15 ? null : m;
}

/** Årskostnad för den angivna användningen. Okända avgifter räknas som 0 och redovisas, så att
 *  siffran då är ett golv. */
function cardCost(p, abroad, debt) {
  const parts = [], unknown = [];
  const add = (k, amount, label) => {
    const v = val(p, k);
    if (v == null) unknown.push(label);
    else if (amount(v)) parts.push(amount(v));
  };
  if (val(p, "annual_fee_sek") == null && val(p, "monthly_fee_sek") != null) parts.push(val(p, "monthly_fee_sek") * 12);
  else add("annual_fee_sek", (v) => v, "årsavgift");
  if (extraMonthly(p) != null) parts.push(extraMonthly(p) * 12);
  if (abroad) add("currency_fee_percent", (v) => v / 100 * abroad, "valutapåslag");
  if (debt) {
    if (val(p, "card_type") === "betalkort") return null;   // går inte att delbetala
    add("rate_percent", (v) => v / 100 * debt, "ränta");
    add("invoice_fee_sek", (v) => v * 12, "aviavgift");
  }
  return { total: parts.reduce((a, b) => a + b, 0), unknown };
}

function cardDetail(b, p) {
  const rows = Object.entries(C_DETAIL).map(([k, label]) => {
    const f = p.fields[k];
    if (!f || f.value == null) return "";
    let v = f.value;
    if (C_PCT.has(k)) v = pct(v);
    else if (C_KR.has(k)) v = `${kr.format(v)} kr`;
    else if (typeof v === "boolean") v = v ? "Ja" : "Nej";
    else if (k === "interest_free_days") v = `${v} dagar`;
    else if (k === "min_age") v = `${v} år`;
    return `<dt>${label}</dt><dd>${esc(v)} ${quote(b, f)}</dd>`;
  }).join("");
  return `<dl class="terms">${rows}</dl>
    <p class="sources">${b.bank.legal_name && b.bank.legal_name !== b.bank.name ? esc(b.bank.legal_name) + ". " : ""}Senast kontrollerat ${new Date(b.checked_at).toLocaleDateString("sv-SE")}. <a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">Till utgivaren</a></p>`;
}

const hasCardFigures = (p) => ["annual_fee_sek", "monthly_fee_sek", "rate_percent", "currency_fee_percent"].some((k) => val(p, k) != null);

function renderCards() {
  const abroad = num("#c-abroad"), debt = num("#c-debt"), sortKey = $("#c-sort").value;
  const charge = $("#c-charge").checked, open = $("#c-open").checked;
  // Samma kort kan stå på flera utgivares sidor (Eurocard hos SEB); visa den bäst belagda.
  const best = new Map();
  for (const b of K.banks) for (const p of b.products || []) {
    if (!hasCardFigures(p)) continue;
    const k = p.name.toLowerCase(), score = Object.values(p.fields).filter((f) => f.value != null).length;
    if (!best.has(k) || best.get(k) < score) best.set(k, score);
  }
  const items = [];
  for (const b of K.banks) for (const p of b.products || []) {
    if (!hasCardFigures(p)) continue;
    if (p.status === "ej verifierad" && best.get(p.name.toLowerCase()) > Object.values(p.fields).filter((f) => f.value != null).length) continue;
    if (!charge && val(p, "card_type") === "betalkort") continue;
    if (open && val(p, "requires_other_products") === true) continue;
    items.push({ b, p, c: cardCost(p, abroad, debt) });
  }
  // Sparbankerna säljer samma kort (från Entercard) – visa ett erbjudande som en rad.
  const groups = new Map();
  for (const it of items) {
    const k = [it.p.name.toLowerCase(), ...["annual_fee_sek", "monthly_fee_sek", "rate_percent", "currency_fee_percent", "example_effective_rate_percent"].map((f) => val(it.p, f))].join("|");
    if (groups.has(k)) groups.get(k).also.push(it.b);
    else groups.set(k, Object.assign(it, { also: [] }));
  }
  items.length = 0;
  items.push(...groups.values());
  const key = {
    cost: (x) => x.c?.total, annual: (x) => val(x.p, "annual_fee_sek") ?? (val(x.p, "monthly_fee_sek") != null ? val(x.p, "monthly_fee_sek") * 12 : null),
    fx: (x) => val(x.p, "currency_fee_percent"), rate: (x) => val(x.p, "rate_percent"),
  }[sortKey];
  items.sort((x, y) => {
    // Vid årskostnad: kort där allt som behövs är känt först.
    if (sortKey === "cost" && x.c && y.c && !x.c.unknown.length !== !y.c.unknown.length) return x.c.unknown.length ? 1 : -1;
    const a = key(x), c = key(y);
    if (a == null && c == null) return x.b.bank.name.localeCompare(y.b.bank.name, "sv");
    if (a == null) return 1;
    if (c == null) return -1;
    return a - c;
  });
  const tb = $("#cards tbody");
  tb.replaceChildren();
  const muted = '<span class="muted">–</span>';
  for (const { b, p, c, also } of items) {
    const tr = document.createElement("tr");
    tr.className = "mtg-row";
    const status = p.status !== "verifierad" ? ` <span class="tag part" title="${p.status}">?</span>` : "";
    const name = esc(issuer(b)) + (also.length ? ` <span class="muted small">och ${also.length} till</span>` : "");
    const cost = !c ? '<span class="muted small">kan inte delbetalas</span>'
      : `<b>${c.unknown.length ? "minst " : ""}${kr.format(Math.round(c.total))} kr</b>${c.unknown.length ? `<br><span class="muted small">${esc(c.unknown.join(", "))} okänd</span>` : ""}`;
    const annual = val(p, "annual_fee_sek"), monthly = annual != null ? extraMonthly(p) : val(p, "monthly_fee_sek");
    const fee = annual != null ? `${kr.format(annual)} kr` + (monthly ? `<br><span class="muted small">+ ${kr.format(monthly)} kr/mån</span>` : "")
      : monthly != null ? `${kr.format(monthly)} kr/mån` : muted;
    const r = val(p, "rate_percent"), e = val(p, "example_effective_rate_percent");
    const rate = val(p, "card_type") === "betalkort" ? '<span class="muted small">betalkort</span>'
      : r == null ? muted : `${pct(r)}${e != null ? `<br><span class="muted small">eff. ${pct(e)}</span>` : ""}`;
    const incl = [val(p, "interest_free_days") != null ? `${val(p, "interest_free_days")} räntefria dagar` : null,
      val(p, "travel_insurance") === true ? "reseförsäkring" : null, val(p, "bonus")].filter(Boolean).map(esc).join("<br>");
    tr.innerHTML = `<th scope="row"><button class="expand" aria-expanded="false">${name}</button>${status}<br><span class="muted">${esc(p.name)}</span></th>
      <td class="num">${cost}</td><td class="num">${fee}</td>
      <td class="num">${val(p, "currency_fee_percent") == null ? muted : pct(val(p, "currency_fee_percent"))}</td>
      <td class="num">${rate}</td><td class="small">${incl || muted}</td>`;
    const det = document.createElement("tr");
    det.className = "mtg-detail";
    det.hidden = true;
    tr.querySelector(".expand").addEventListener("click", (ev) => {
      if (!det.firstChild) det.innerHTML = `<td colspan="6">${also.length ? `<p class="sources">Samma kort hos ${[b, ...also].map((x) => `<a href="${x.bank.homepage}" rel="noopener nofollow" target="_blank">${esc(issuer(x))}</a>`).join(", ")}.</p>` : ""}${cardDetail(b, p)}</td>`;
      det.hidden = !det.hidden;
      ev.currentTarget.setAttribute("aria-expanded", String(!det.hidden));
    });
    tb.append(tr, det);
  }
  $("#c-note").textContent = `${items.length} erbjudanden. "Per år för dig" = årsavgift och kortavgifter, valutapåslag på ${kr.format(abroad)} kr${debt ? `, och ränta och aviavgifter på en skuld på ${kr.format(debt)} kr` : ""}. "minst" = någon avgift står inte på utgivarens sidor och är räknad som 0. Uttagsavgifter ingår inte. ? = inte helt verifierat.`;
}

function renderCardsMissing() {
  const miss = K.banks.filter((b) => !(b.products || []).some(hasCardFigures));
  const el = $("#c-missing");
  el.hidden = !miss.length;
  el.querySelector("summary").textContent = `${miss.length} utgivare kunde inte läsas automatiskt`;
  el.querySelector("ul").innerHTML = miss.map((b) => `<li><a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">${esc(issuer(b))}</a></li>`).join("");
}

function showLoanView() {
  const v = document.querySelector('input[name="view"]:checked').value;
  $("#v-loans").hidden = v !== "loans";
  $("#v-cards").hidden = v !== "cards";
  // Adressen följer vyn (#kort), så att kortjämförelsen går att länka till.
  history.replaceState(null, "", v === "cards" ? "#kort" : location.pathname + location.search);
}

if (location.hash === "#kort") document.querySelector('input[name="view"][value="cards"]').checked = true;
showLoanView();
document.querySelectorAll('input[name="view"]').forEach((i) => i.addEventListener("change", showLoanView));

fetch("data/cards.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : { banks: [] }).catch(() => ({ banks: [] })).then((d) => {
  K = d;
  renderCards();
  renderCardsMissing();
  let t;
  for (const s of ["#c-abroad", "#c-debt"]) {
    $(s).addEventListener("input", () => { clearTimeout(t); t = setTimeout(renderCards, 200); });
    $(s).addEventListener("change", () => { const v = num(s); $(s).value = kr.format(v); });
  }
  ["#c-sort", "#c-charge", "#c-open"].forEach((s) => $(s).addEventListener("change", renderCards));
});
