"use strict";

const COUNTRY = { SE: "Sverige", LT: "Litauen", NO: "Norge", DK: "Danmark", FI: "Finland", DE: "Tyskland", MT: "Malta", LV: "Lettland", EE: "Estland", NL: "Nederländerna", IE: "Irland" };
const ACC_DETAIL = {
  company_forms: "Företagsformer",
  new_company_terms: "Nystartade",
  user_terms: "Behörigheter",
  fee_terms: "Avgifter och innehåll",
  bankgiro: "Bankgiro",
  account_interest_percent: "Ränta på kontot",
  requirements: "Krav för att bli kund",
  guarantee_country: "Insättningsgaranti",
};

let A = null, S = null, F = null, P = null, X = null;
const val = (p, k) => (p.fields[k] || {}).value ?? null;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const kr = new Intl.NumberFormat("sv-SE", { maximumFractionDigits: 0 });

/** Ja/nej/okänt med symbol och text – aldrig bara färg. */
function yn(v) {
  if (v === true) return '<span class="yn yes">✓ Ja</span>';
  if (v === false) return '<span class="yn no">✗ Nej</span>';
  return '<span class="yn unk">? Okänt</span>';
}

/** Bankens mest generösa svar över dess produkter (ett ja i något paket räcker). */
function any(b, k) {
  const vs = (b.products || []).map((p) => val(p, k));
  if (vs.includes(true)) return true;
  if (vs.includes(false)) return false;
  return null;
}

function minFee(b) {
  const vs = (b.products || []).map((p) => val(p, "monthly_fee_sek")).filter((v) => v != null);
  return vs.length ? Math.min(...vs) : null;
}

function forms(b) {
  return (b.products || []).map((p) => (val(p, "company_forms") || "").toLowerCase()).join(", ");
}

function quote(b, f) {
  if (!f || !f.quote || f.value == null) return "";
  const src = b.sources[f.source];
  return `<q>${esc(f.quote)}</q>${src ? ` <a href="${src.url}" rel="noopener nofollow" target="_blank">källa</a>` : ""}`;
}

function accDetail(b) {
  const prods = (b.products || []).map((p) => {
    const terms = Object.entries(ACC_DETAIL).map(([k, label]) => {
      const f = p.fields[k];
      if (!f || f.value == null) return "";
      let v = f.value;
      if (typeof v === "boolean") v = v ? "Ja" : "Nej";
      else if (k === "account_interest_percent") v = pct(v);
      else if (k === "guarantee_country") v = COUNTRY[v] || v;
      return `<dt>${label}</dt><dd>${esc(v)} ${quote(b, f)}</dd>`;
    }).join("");
    const fee = val(p, "monthly_fee_sek");
    return `<h3 class="prod">${esc(p.name)}${fee != null ? ` – ${kr.format(fee)} kr/mån` : ""}</h3><dl class="terms">${terms}</dl>`;
  }).join("");
  return `${prods}<p class="sources">${b.bank.legal_name && b.bank.legal_name !== b.bank.name ? esc(b.bank.legal_name) + ". " : ""}Senast kontrollerat ${new Date(b.checked_at).toLocaleDateString("sv-SE")}. <a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">Till banken</a></p>`;
}

function renderAccounts() {
  const form = $("#form").value;
  const f = { new: $("#f-new").checked, online: $("#f-online").checked, users: $("#f-users").checked, swish: $("#f-swish").checked };
  const items = A.banks.filter((b) => (b.products || []).length)
    .filter((b) => !form || forms(b).includes(form))
    .filter((b) => (!f.new || any(b, "accepts_new_companies") === true) && (!f.online || any(b, "open_online") === true)
      && (!f.users || any(b, "multiple_users") === true) && (!f.swish || any(b, "swish") === true))
    .sort((a, b) => (minFee(a) ?? 1e9) - (minFee(b) ?? 1e9) || a.bank.name.localeCompare(b.bank.name, "sv"));
  const tb = $("#acc tbody");
  tb.replaceChildren();
  for (const b of items) {
    const tr = document.createElement("tr");
    tr.className = "mtg-row";
    const fee = minFee(b);
    tr.innerHTML = `<th scope="row"><button class="expand" aria-expanded="false">${esc(b.bank.name)}</button></th>
      <td>${yn(any(b, "accepts_new_companies"))}</td><td>${yn(any(b, "open_online"))}</td>
      <td>${yn(any(b, "multiple_users"))}</td><td>${yn(any(b, "swish"))}</td>
      <td class="num">${fee == null ? '<span class="muted">okänt</span>' : fee === 0 ? "0" : kr.format(fee)}</td>`;
    const det = document.createElement("tr");
    det.className = "mtg-detail";
    det.hidden = true;

    tr.querySelector(".expand").addEventListener("click", (e) => {
      if (!det.firstChild) det.innerHTML = `<td colspan="${6}">${accDetail(b)}</td>`;  // byggs först vid utfällning
      det.hidden = !det.hidden;
      e.currentTarget.setAttribute("aria-expanded", String(!det.hidden));
    });
    tb.append(tr, det);
  }
  $("#acc-note").textContent = `${items.length} banker. "Okänt" betyder att banken inte skriver det uttryckligen på sina sidor – fråga banken. Klicka på en bank för villkor och källor.`;
}

const BIND_LABEL = (m) => m == null ? "okänt" : m === 0 ? "ingen" : m % 12 === 0 ? `${m / 12} år` : `${m} mån`;
const WD = { "fria": "fria", "begränsade": "begränsade", "mot avgift": "mot avgift", "ej tillåtna": "låst" };

function renderSavings() {
  const bind = +document.querySelector('input[name="bind"]:checked').value;
  const items = [];
  for (const b of S.banks) {
    for (const p of b.products || []) {
      const r = val(p, "rate_percent"), m = val(p, "binding_months");
      if (r == null) continue;
      if (bind === 0 && m) continue;
      if (bind > 0 && bind < 999 && (m == null || m > bind)) continue;
      items.push({ b, p, r, m });
    }
  }
  items.sort((x, y) => y.r - x.r);
  const tb = $("#sav tbody");
  tb.replaceChildren();
  for (const { b, p, r, m } of items) {
    const tr = document.createElement("tr");
    const gc = val(p, "guarantee_country");
    const status = p.status !== "verifierad" ? ` <span class="tag part" title="${p.status}">?</span>` : "";
    tr.innerHTML = `<th scope="row"><b>${esc(b.bank.name)}</b><br><span class="muted">${esc(p.name)}</span></th>
      <td class="num">${pct(r)}${status}</td><td>${BIND_LABEL(m)}</td><td>${WD[val(p, "withdrawals")] || "okänt"}</td>
      <td>${gc ? esc(COUNTRY[gc] || gc) : "okänt"}</td>`;
    tr.title = (p.fields.rate_percent.quote || "");
    tb.append(tr);
  }
  $("#sav-note").textContent = `${items.length} konton. Räntan är nominell årsränta enligt bankens sida; villkor för belopp och uttag finns hos banken. ? = inte helt verifierad.`;
}

/** Banker som inte gick att läsa – bara för den vy som visas (Utlandsbetalningar har en egen lista, Valutasäkring ingen). */
const MISSING = {
  accounts: [() => A, (b) => (b.products || []).length, "erbjuder företagskonton"],
  savings: [() => S, (b) => (b.products || []).some((p) => val(p, "rate_percent") != null), "erbjuder sparkonton för företag"],
  financing: [() => F, (b) => (b.products || []).length, "lånar ut till företag"],
};

function renderMissing(v) {
  const el = $("#missing");
  const m = MISSING[v];
  const d = m && m[0]();
  const miss = d ? d.banks.filter((b) => !m[1](b)) : [];
  el.hidden = !miss.length;
  if (!miss.length) return;
  el.querySelector("summary").textContent = `${miss.length} ${miss.length === 1 ? "bank" : "banker"} kunde inte läsas automatiskt`;
  el.querySelector("p").textContent = `De här bankerna ${m[2]}, men uppgifterna gick inte att läsa eller belägga automatiskt. Kontrollera dem direkt hos banken.`;
  el.querySelector("ul").innerHTML = miss.sort((a, b) => a.bank.name.localeCompare(b.bank.name, "sv"))
    .map((b) => `<li><a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">${esc(b.bank.name)}</a></li>`).join("");
}

function showView() {
  const v = document.querySelector('input[name="view"]:checked').value;
  $("#v-accounts").hidden = v !== "accounts";
  $("#v-savings").hidden = v !== "savings";
  $("#v-financing").hidden = v !== "financing";
  $("#v-payments").hidden = v !== "payments";
  $("#v-hedge").hidden = v !== "hedge";
  if (A) renderMissing(v);
  try { localStorage.setItem("foretag-view", v); } catch (e) { /* privat läge */ }
}

/* ---------- Finansiering ---------- */

const FIN_DETAIL = {
  cost_terms: "Kostnad", effective_rate_percent: "Effektiv ränta", min_months_in_business: "Tid i drift",
  min_turnover_sek: "Lägsta omsättning", collateral: "Säkerhet", payout_speed: "Utbetalning",
  company_forms: "Företagsformer", requirements: "Övriga krav",
};
const krAmt = (v) => v == null ? null : v >= 1e6 ? `${(v / 1e6).toLocaleString("sv-SE", { maximumFractionDigits: 1 })} mkr` : `${kr.format(v)} kr`;
const months = (m) => m == null ? null : m % 12 === 0 ? `${m / 12} år` : `${m} mån`;
const range = (a, b, f) => a == null && b == null ? '<span class="muted">–</span>' : a != null && b != null ? `${f(a)}–${f(b)}` : a != null ? `från ${f(a)}` : `upp till ${f(b)}`;

function finCost(p) {
  const r = val(p, "rate_from_percent"), m = val(p, "monthly_fee_percent"), e = val(p, "effective_rate_percent");
  const parts = [];
  if (r != null) parts.push(`från ${pct(r, 2)} per år`);
  if (m != null) parts.push(`från ${pct(m, 2)} per månad`);
  if (e != null) parts.push(`effektiv ${pct(e, 2)}`);
  return parts.length ? parts.join("<br>") : '<span class="muted">individuell</span>';
}

function finDetail(b, p) {
  const rows = Object.entries(FIN_DETAIL).map(([k, label]) => {
    const f = p.fields[k];
    if (!f || f.value == null) return "";
    let v = f.value;
    if (k === "min_months_in_business") v = months(v);
    else if (k === "min_turnover_sek") v = krAmt(v);
    else if (k === "effective_rate_percent") v = pct(v);
    return `<dt>${label}</dt><dd>${esc(v)} ${quote(b, f)}</dd>`;
  }).join("");
  const main = ["min_amount_sek", "max_amount_sek", "term_max_months", "rate_from_percent", "monthly_fee_percent", "accepts_new_companies", "personal_guarantee"]
    .map((k) => p.fields[k]?.value != null && p.fields[k].quote ? `<dt>${{ min_amount_sek: "Lägsta belopp", max_amount_sek: "Högsta belopp", term_max_months: "Längsta löptid", rate_from_percent: "Årsränta från", monthly_fee_percent: "Månadskostnad från", accepts_new_companies: "Nystartade", personal_guarantee: "Personlig borgen" }[k]}</dt><dd>${quote(b, p.fields[k])}</dd>` : "").join("");
  return `<dl class="terms">${rows}${main}</dl><p class="sources">${b.bank.legal_name && b.bank.legal_name !== b.bank.name ? esc(b.bank.legal_name) + ". " : ""}Senast kontrollerat ${new Date(b.checked_at).toLocaleDateString("sv-SE")}. <a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">Till långivaren</a></p>`;
}

function renderFinMarket() {
  const c = F.context || {};
  const card = (id, title) => c[id] ? `<article class="region"><h2>${title}</h2><div class="hero"><span class="hero-num">${pct(c[id].value)}</span>
    <span class="hero-label">${esc(c[id].name)}${id !== "se_policy" ? ", " + new Date(c[id].date).toLocaleDateString("sv-SE", { month: "long", year: "numeric" }) : ""}</span>
    <span class="hero-sub">${pp(c[id].chg_1y)} på ett år · SCB</span></div></article>` : "";
  $("#fin-market").innerHTML = card("se_corp_new_all", "Snittränta nya företagslån") + card("se_soletrader_new_all", "Enskilda näringsidkare")
    + card("se_corp_kontokredit", "Kontokredit") + card("se_policy", "Styrräntan");
}

function renderFinancing() {
  const type = $("#fin-type").value;
  const amount = parseInt(($("#fin-amount").value || "").replace(/\D/g, ""), 10) || null;
  const f = { new: $("#fin-new").checked, price: $("#fin-price").checked };
  const items = [];
  for (const b of F.banks) for (const p of b.products || []) {
    if (val(p, "product_type") == null && val(p, "max_amount_sek") == null) continue;
    if (type && val(p, "product_type") !== type) continue;
    if (amount != null) {
      const lo = val(p, "min_amount_sek"), hi = val(p, "max_amount_sek");
      if ((lo != null && amount < lo) || (hi != null && amount > hi)) continue;
    }
    if (f.new && val(p, "accepts_new_companies") !== true) continue;
    if (f.price && val(p, "rate_from_percent") == null && val(p, "monthly_fee_percent") == null && val(p, "effective_rate_percent") == null) continue;
    items.push({ b, p });
  }
  items.sort((x, y) => (val(y.p, "max_amount_sek") ?? -1) - (val(x.p, "max_amount_sek") ?? -1) || x.b.bank.name.localeCompare(y.b.bank.name, "sv"));
  const tb = $("#fin tbody");
  tb.replaceChildren();
  for (const { b, p } of items) {
    const tr = document.createElement("tr");
    tr.className = "mtg-row";
    const t = val(p, "product_type");
    tr.innerHTML = `<th scope="row"><button class="expand" aria-expanded="false">${esc(b.bank.name)}</button><br><span class="muted">${esc(p.name)}${t ? " · " + esc(t) : ""}</span></th>
      <td>${range(val(p, "min_amount_sek"), val(p, "max_amount_sek"), krAmt)}</td>
      <td>${range(val(p, "term_min_months"), val(p, "term_max_months"), months)}</td>
      <td>${finCost(p)}</td><td>${yn(val(p, "accepts_new_companies"))}</td>
      <td>${val(p, "personal_guarantee") === true ? '<span class="yn no">Krävs</span>' : val(p, "personal_guarantee") === false ? '<span class="yn yes">✓ Ingen</span>' : '<span class="yn unk">? Okänt</span>'}</td>`;
    const det = document.createElement("tr");
    det.className = "mtg-detail";
    det.hidden = true;
    tr.querySelector(".expand").addEventListener("click", (e) => {
      if (!det.firstChild) det.innerHTML = `<td colspan="6">${finDetail(b, p)}</td>`;
      det.hidden = !det.hidden;
      e.currentTarget.setAttribute("aria-expanded", String(!det.hidden));
    });
    tb.append(tr, det);
  }
  $("#fin-note").textContent = `${items.length} erbjudanden. Kostnaden visas så som långivaren själv anger den – en månadskostnad på 1,5 % motsvarar mycket mer än 1,5 % per år. "Okänt" betyder att långivaren inte skriver det uttryckligen.`;
}

/* ---------- Utlandsbetalningar ---------- */

const CATS = [["out_sepa", "#p-out-sepa"], ["out_other", "#p-out-other"], ["in_sepa", "#p-in-sepa"], ["in_other", "#p-in-other"]];
const count = (sel) => parseInt(($(sel).value || "").replace(/\D/g, ""), 10) || 0;
const sure = (p, k) => p.status === "verifierad" || (p.fields[k] || {}).status === "belagt";

/** Riktning och typ: ur fälten, annars ur produktens namn. null = intern överföring mellan tjänstens egna konton. */
function payKind(p) {
  const n = p.name.toLowerCase();
  const dir = (val(p, "direction") || (/inkommande|ankommande|ta emot|mottag|receive/.test(n) ? "inkommande" : "utgående")) === "inkommande" ? "in" : "out";
  let t = val(p, "payment_type");
  if (t === "överföring via betaltjänst" && /mellan|samma valuta|-konton|-konto\b/.test(n)) return null;
  if (!t || t === "överföring via betaltjänst") {
    t = /sepa|eu-betal|europabetal|i euro\b/.test(n) ? "SEPA-betalning" : /övriga|annan valuta|swift|utlandsbetal|kontoinsättning|internationell/.test(n) ? "utlandsbetalning" : null;
  }
  return { dir, types: t === "SEPA-betalning" ? ["sepa"] : t === "utlandsbetalning" ? ["other"] : ["sepa", "other"], specific: !!t };
}

/** Avgiften för en betalning av beloppet, eller null om den inte går att räkna ut. */
function payFee(p, amount, cat) {
  const fix = val(p, "fee_fixed_sek"), pc = val(p, "fee_percent");
  if (fix == null && pc == null) return null;
  const lo = val(p, "amount_from_sek"), hi = val(p, "amount_to_sek");
  if ((lo != null && amount < lo) || (hi != null && amount > hi)) return null;   // priset gäller ett annat belopp
  let f = pc != null ? pc * amount / 100 : 0;
  if (pc != null && val(p, "fee_min_sek") != null) f = Math.max(f, val(p, "fee_min_sek"));
  if (pc != null && val(p, "fee_max_sek") != null) f = Math.min(f, val(p, "fee_max_sek"));
  f += fix || 0;
  if (cat === "out_other") f += val(p, "third_currency_fee_sek") || 0;   // de flesta "övriga" är i en tredje valuta
  const unsure = !sure(p, fix != null ? "fee_fixed_sek" : "fee_percent");
  return { fee: f, unsure, p };
}

const NO_PACKAGE = /^(utan paket|alla paket|inget|ingen|-)?$/i;

/** En rad per bank och paket: billigaste kända avgift per betalningstyp. */
function payRows(amount) {
  const rows = [], miss = [];
  for (const b of P.banks) {
    const prods = (b.products || []).map((p) => ({ p, k: payKind(p) })).filter((x) => x.k);
    if (!prods.some(({ p }) => val(p, "fee_fixed_sek") != null || val(p, "fee_percent") != null)) { miss.push(b); continue; }
    const pkgs = [...new Set(prods.map(({ p }) => (val(p, "package") || "").trim()).filter((x) => !NO_PACKAGE.test(x)))];
    for (const pkg of pkgs.length ? pkgs : [""]) {
      const mine = prods.filter(({ p }) => { const x = (val(p, "package") || "").trim(); return NO_PACKAGE.test(x) || x === pkg; });
      const fees = {};
      for (const [cat] of CATS) {
        const [dir, type] = cat.split("_");
        const hit = mine.filter(({ k }) => k.dir === dir && k.types.includes(type));
        // en produkt för just den typen går före en allmän – även när dess pris saknas
        const pool = hit.some(({ k }) => k.specific) ? hit.filter(({ k }) => k.specific) : hit;
        const cands = pool.map(({ p }) => payFee(p, amount, cat)).filter(Boolean).sort((x, y) => x.fee - y.fee);
        fees[cat] = cands[0] || null;
      }
      const fxs = mine.map(({ p }) => val(p, "fx_markup_percent")).filter((v) => v != null);
      const pkgFee = Math.max(-1, ...mine.map(({ p }) => val(p, "package_fee_sek_month") ?? -1));
      rows.push({ b, pkg, fees, fx: fxs.length ? Math.max(...fxs) : null, pkgFee: pkgFee >= 0 ? pkgFee : null, prods: mine.map(({ p }) => p) });
    }
  }
  return { rows, miss };
}

function payDetail(r) {
  const lines = r.prods.map((p) => {
    const parts = [["fee_fixed_sek", "avgift"], ["fee_percent", "avgift i procent"], ["fee_min_sek", "lägst"], ["fee_max_sek", "högst"],
      ["third_currency_fee_sek", "tillägg tredjelandsvaluta"], ["express_fee_sek", "express"], ["our_fee_sek", "OUR (du betalar alla avgifter)"],
      ["fx_markup_percent", "växlingspåslag"], ["package_fee_sek_month", "paketet"]]
      .filter(([k]) => p.fields[k]?.value != null)
      .map(([k, l]) => `<dt>${l}</dt><dd>${k.endsWith("percent") ? pct(p.fields[k].value) : kr.format(p.fields[k].value) + (k === "package_fee_sek_month" ? " kr/mån" : " kr")} ${quote(r.b, p.fields[k])}</dd>`).join("");
    const t = val(p, "terms");
    return `<h3 class="prod">${esc(p.name)}${p.status !== "verifierad" ? ` <span class="tag part">${esc(p.status)}</span>` : ""}</h3><dl class="terms">${parts}${t ? `<dt>Villkor</dt><dd>${esc(t)}</dd>` : ""}</dl>`;
  }).join("");
  return `${lines}<p class="sources">Senast kontrollerat ${new Date(r.b.checked_at).toLocaleDateString("sv-SE")}. <a href="${r.b.bank.homepage}" rel="noopener nofollow" target="_blank">Till ${esc(r.b.bank.name)}</a></p>`;
}

function renderPayments() {
  if (!P || !P.banks.length) return;
  const amount = count("#p-amount") || 25000;
  const n = Object.fromEntries(CATS.map(([c, sel]) => [c, count(sel)]));
  const payments = Object.values(n).reduce((a, b) => a + b, 0);
  const { rows, miss } = payRows(amount);
  for (const r of rows) {
    r.missing = CATS.filter(([c]) => n[c] && !r.fees[c]).map(([c]) => c);
    r.total = CATS.reduce((s, [c]) => s + (n[c] && r.fees[c] ? n[c] * r.fees[c].fee : 0), 0) + (r.fx ? payments * amount * r.fx / 100 : 0);
    r.unsure = CATS.some(([c]) => n[c] && r.fees[c]?.unsure);
  }
  rows.sort((x, y) => x.missing.length - y.missing.length || x.total - y.total || x.b.bank.name.localeCompare(y.b.bank.name, "sv"));
  const cell = (f) => f ? `${f.fee === 0 ? "0" : kr.format(Math.round(f.fee))} kr${f.unsure ? ' <span class="tag part" title="inte helt belagt">?</span>' : ""}` : '<span class="muted">okänt</span>';
  const tb = $("#pay tbody");
  tb.replaceChildren();
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.className = "mtg-row";
    const pkg = r.pkg ? `${esc(r.pkg)}${r.pkgFee != null ? ` · ${kr.format(r.pkgFee)} kr/mån` : ""}` : r.pkgFee != null ? `paket ${kr.format(r.pkgFee)} kr/mån` : "";
    const tot = r.missing.length ? `<span class="muted">minst</span> ${kr.format(Math.round(r.total))} kr` : `<b>${kr.format(Math.round(r.total))} kr</b>`;
    tr.innerHTML = `<th scope="row"><button class="expand" aria-expanded="false">${esc(r.b.bank.name)}</button>${pkg ? `<br><span class="muted">${pkg}</span>` : ""}</th>
      <td class="num">${tot}${r.fx == null ? '<br><span class="muted small">+ växlingspåslag</span>' : ""}</td>
      <td class="num">${cell(r.fees.out_sepa)}</td><td class="num">${cell(r.fees.out_other)}</td>
      <td class="num">${cell(r.fees.in_sepa)} / ${cell(r.fees.in_other)}</td>
      <td class="num">${r.fx == null ? '<span class="muted">okänt</span>' : pct(r.fx)}</td>`;
    const det = document.createElement("tr");
    det.className = "mtg-detail";
    det.hidden = true;
    tr.querySelector(".expand").addEventListener("click", (e) => {
      if (!det.firstChild) det.innerHTML = `<td colspan="6">${payDetail(r)}</td>`;
      det.hidden = !det.hidden;
      e.currentTarget.setAttribute("aria-expanded", String(!det.hidden));
    });
    tb.append(tr, det);
  }
  $("#pay-note").textContent = `${rows.length} erbjudanden. Kostnaden gäller betalningar via internetbanken eller appen enligt prislistan för företag, före eventuella fria betalningar eller avtalspriser. "Ta emot" visar SEPA / övriga. Växlingspåslaget räknas med där det står i procent. De flesta banker anger det inte, och då tillkommer det. Paketavgiften räknas inte med, eftersom de flesta företag redan betalar för ett kontopaket – jämför paketen under Hitta bank. Klicka på en rad för priser och källor. ? = inte helt belagt.`;
  const el = $("#pay-missing");
  el.hidden = !miss.length;
  el.querySelector("summary").textContent = `${miss.length} banker och tjänster saknar publicerade priser`;
  el.querySelector("ul").innerHTML = miss.sort((a, b) => a.bank.name.localeCompare(b.bank.name, "sv"))
    .map((b) => `<li><a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">${esc(b.bank.name)}</a></li>`).join("");
}

/* ---------- Valutasäkring: teoretisk terminskurs ---------- */

const RATE_KEYS = { SEK: ["se_tb3m", "se_gvb2y"], EUR: ["eu_y3m", "eu_y2y"], USD: ["us_t3m", "us_t2y"] };
const dec = (v, d = 4) => v.toLocaleString("sv-SE", { minimumFractionDigits: d, maximumFractionDigits: d });
const parseDec = (s) => parseFloat(String(s || "").replace(/\s/g, "").replace(",", ".")) || null;

/** Ränta för löptiden: 3-månadersräntan, och mellan 3 månader och 2 år linjärt mot 2-årsräntan. */
function rateFor(cur, m) {
  const L = X.rates.latest, [k3, k2] = RATE_KEYS[cur];
  if (L[k3] == null) return null;
  return m <= 3 || L[k2] == null ? L[k3] : L[k3] + (L[k2] - L[k3]) * (m - 3) / 21;
}

function renderHedge() {
  const res = $("#h-result");
  if (!X || !X.rates || !X.rates.latest) { res.innerHTML = '<p class="muted">Kurser och räntor kunde inte läsas in just nu.</p>'; return; }
  const cur = $("#h-cur").value, m = +$("#h-months").value, side = $("#h-side").value;
  $("#h-unit").textContent = cur;
  const amount = count("#h-amount"), quoteRate = parseDec($("#h-quote").value);
  const spot = X.latest[cur], rs = rateFor("SEK", m), rf = rateFor(cur, m);
  if (!spot || rs == null || rf == null) { res.innerHTML = ""; return; }
  const t = m / 12, fwd = spot * Math.pow(1 + rs / 100, t) / Math.pow(1 + rf / 100, t);
  const diff = (fwd / spot - 1) * 100;
  let html = `<p>Dagens referenskurs är <b>${dec(spot)} kr</b> per ${cur} (ECB, ${new Date(X.date).toLocaleDateString("sv-SE")}). Med ${pct(rs)} svensk och ${pct(rf)} ${cur === "EUR" ? "euro" : "dollar"}ränta på ${m} ${m === 1 ? "månad" : "månader"} blir den teoretiska terminskursen <b>${dec(fwd)} kr</b>, ${Math.abs(diff).toLocaleString("sv-SE", { maximumFractionDigits: 2 })} % ${diff < 0 ? "lägre" : "högre"} än i dag.</p>`;
  if (quoteRate) {
    const markup = side === "buy" ? (quoteRate / fwd - 1) * 100 : (fwd / quoteRate - 1) * 100;
    const cost = (side === "buy" ? quoteRate - fwd : fwd - quoteRate) * (amount || 0);
    if (Math.abs(quoteRate / spot - 1) > 0.15) {
      html = `<p class="verdict bad">Kursen ${dec(quoteRate)} ligger långt från dagens kurs. Kontrollera att den gäller kronor per en ${cur}.</p>` + html;
    } else if (markup > 0.2) {
      html = `<p class="verdict bad"><b>Påslaget är ungefär ${markup.toLocaleString("sv-SE", { maximumFractionDigits: 2 })} %</b>${amount ? `, eller cirka <b>${kr.format(Math.round(cost))} kr</b> på ${kr.format(amount)} ${cur}` : ""}. Fråga banken om en bättre kurs eller jämför med en annan bank.</p>` + html;
    } else {
      html = `<p class="verdict ok"><b>Kursen är rimlig.</b> Den ligger inom ${Math.max(markup, 0).toLocaleString("sv-SE", { maximumFractionDigits: 2 })} % från den teoretiska kursen – mindre än vad räntor och dagens kursrörelser kan förklara.</p>` + html;
    }
  } else {
    html += `<p class="muted small">Fyll i kursen som banken erbjuder för att se ungefär hur stort påslaget är.</p>`;
  }
  res.innerHTML = html;
}

const empty = { banks: [] };
Promise.all([
  fetch("data/business_accounts.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : empty).catch(() => empty),
  fetch("data/business_savings.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : empty).catch(() => empty),
  fetch("data/business_financing.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : empty).catch(() => empty),
  fetch("data/business_transfers.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : empty).catch(() => empty),
  fetch("data/fx.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : null).catch(() => null),
]).then(([acc, sav, fin, pay, fx]) => {
  A = acc; S = sav; F = fin; P = pay; X = fx;
  try {
    const v = localStorage.getItem("foretag-view");
    if (["accounts", "savings", "financing", "payments", "hedge"].includes(v)) document.querySelector(`input[name="view"][value="${v}"]`).checked = true;
  } catch (e) { /* ingen lagring */ }
  showView();
  renderAccounts();
  renderSavings();
  renderFinMarket();
  renderFinancing();
  renderPayments();
  renderHedge();
  const at = acc.generated_at || sav.generated_at;
  if (at) $("#updated").textContent = `Data uppdaterad ${new Date(at).toLocaleString("sv-SE", { dateStyle: "long", timeStyle: "short" })}.`;
  document.querySelectorAll('input[name="view"]').forEach((i) => i.addEventListener("change", showView));
  ["#form", "#f-new", "#f-online", "#f-users", "#f-swish"].forEach((s) => $(s).addEventListener("change", renderAccounts));
  document.querySelectorAll('input[name="bind"]').forEach((i) => i.addEventListener("change", renderSavings));
  ["#fin-type", "#fin-new", "#fin-price"].forEach((s) => $(s).addEventListener("change", renderFinancing));
  ["#p-amount", "#p-out-sepa", "#p-out-other", "#p-in-sepa", "#p-in-other"].forEach((s) => $(s).addEventListener("input", (e) => {
    const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
    e.target.value = Number.isFinite(n) ? kr.format(n) : "";
    renderPayments();
  }));
  ["#h-side", "#h-cur", "#h-months"].forEach((s) => $(s).addEventListener("change", renderHedge));
  ["#h-amount", "#h-quote"].forEach((s) => $(s).addEventListener("input", renderHedge));
  let finTimer;
  $("#fin-amount").addEventListener("input", (e) => {
    const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
    e.target.value = n ? kr.format(n) : "";
    clearTimeout(finTimer);
    finTimer = setTimeout(renderFinancing, 200);
  });
});
