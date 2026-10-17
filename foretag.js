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

let A = null, S = null, F = null;
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

function renderMissing() {
  const seen = new Set();
  const miss = [];
  for (const [d, ok] of [[A, (b) => (b.products || []).length], [S, (b) => (b.products || []).some((p) => val(p, "rate_percent") != null)], [F, (b) => (b.products || []).length]]) {
    for (const b of d.banks) if (!ok(b) && !seen.has(b.bank.name)) { seen.add(b.bank.name); miss.push(b); }
  }
  const el = $("#missing");
  el.hidden = !miss.length;
  el.querySelector("summary").textContent = `${miss.length} banker kunde inte läsas automatiskt`;
  el.querySelector("ul").innerHTML = miss.sort((a, b) => a.bank.name.localeCompare(b.bank.name, "sv"))
    .map((b) => `<li><a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">${esc(b.bank.name)}</a></li>`).join("");
}

function showView() {
  const v = document.querySelector('input[name="view"]:checked').value;
  $("#v-accounts").hidden = v !== "accounts";
  $("#v-savings").hidden = v !== "savings";
  $("#v-financing").hidden = v !== "financing";
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

const empty = { banks: [] };
Promise.all([
  fetch("data/business_accounts.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : empty).catch(() => empty),
  fetch("data/business_savings.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : empty).catch(() => empty),
  fetch("data/business_financing.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : empty).catch(() => empty),
]).then(([acc, sav, fin]) => {
  A = acc; S = sav; F = fin;
  try {
    const v = localStorage.getItem("foretag-view");
    if (["accounts", "savings", "financing"].includes(v)) document.querySelector(`input[name="view"][value="${v}"]`).checked = true;
  } catch (e) { /* ingen lagring */ }
  showView();
  renderAccounts();
  renderSavings();
  renderFinMarket();
  renderFinancing();
  renderMissing();
  const at = acc.generated_at || sav.generated_at;
  if (at) $("#updated").textContent = `Data uppdaterad ${new Date(at).toLocaleString("sv-SE", { dateStyle: "long", timeStyle: "short" })}.`;
  document.querySelectorAll('input[name="view"]').forEach((i) => i.addEventListener("change", showView));
  ["#form", "#f-new", "#f-online", "#f-users", "#f-swish"].forEach((s) => $(s).addEventListener("change", renderAccounts));
  document.querySelectorAll('input[name="bind"]').forEach((i) => i.addEventListener("change", renderSavings));
  ["#fin-type", "#fin-new", "#fin-price"].forEach((s) => $(s).addEventListener("change", renderFinancing));
  let finTimer;
  $("#fin-amount").addEventListener("input", (e) => {
    const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
    e.target.value = n ? kr.format(n) : "";
    clearTimeout(finTimer);
    finTimer = setTimeout(renderFinancing, 200);
  });
});
