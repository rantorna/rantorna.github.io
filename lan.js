"use strict";

const DETAIL = {
  rate_percent: "Lägsta ränta", rate_max_percent: "Högsta ränta", rate_type: "Räntetyp",
  min_amount_sek: "Lägsta belopp", max_amount_sek: "Högsta belopp",
  term_min_months: "Kortaste löptid", term_max_months: "Längsta löptid",
  setup_fee_sek: "Uppläggningsavgift", monthly_fee_sek: "Aviavgift",
  example_effective_rate_percent: "Representativt exempel", min_age: "Lägsta ålder",
  co_applicant: "Medsökande", requirements: "Krav",
};
const PCT = new Set(["rate_percent", "rate_max_percent", "example_effective_rate_percent"]);
const KR = new Set(["min_amount_sek", "max_amount_sek", "setup_fee_sek", "monthly_fee_sek"]);

const EARMARKED = /energi|sol|grön|miljö|vård|tandvård/i;
let L = null;
const val = (p, k) => (p.fields[k] || {}).value ?? null;
// Förmedlare: enligt långivarens egen text, eller enligt uppslaget av varumärket (plattform).
const broker = (b, p) => val(p, "lender_role") === "låneförmedlare" || b.bank.kind === "plattform";
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const kr = new Intl.NumberFormat("sv-SE", { maximumFractionDigits: 0 });
const krAmt = (v) => v == null ? null : v >= 1e6 ? `${(v / 1e6).toLocaleString("sv-SE", { maximumFractionDigits: 1 })} mkr` : `${kr.format(v)} kr`;
const months = (m) => m == null ? null : m % 12 === 0 ? `${m / 12} år` : `${m} mån`;
const range = (a, b, f) => a == null && b == null ? '<span class="muted">–</span>' : a != null && b != null ? `${f(a)}–${f(b)}` : a != null ? `från ${f(a)}` : `upp till ${f(b)}`;

/** Månadsbetalning för ett annuitetslån. */
function annuity(amount, ratePct, n) {
  const r = ratePct / 1200;
  return r === 0 ? amount / n : amount * r / (1 - (1 + r) ** -n);
}

/** Effektiv årsränta: den ränta där utbetalt belopp (minus uppläggningsavgift) = nuvärdet av alla
 *  månadsbetalningar inklusive aviavgift. Samma metod som konsumentkreditlagen föreskriver. */
function effective(amount, ratePct, n, setup, avi) {
  const pay = annuity(amount, ratePct, n) + avi, net = amount - setup;
  let lo = 0, hi = 0.1;
  for (let k = 0; k < 80; k++) {
    const i = (lo + hi) / 2;
    const pv = i === 0 ? pay * n : pay * (1 - (1 + i) ** -n) / i;
    if (pv > net) lo = i; else hi = i;
  }
  return ((1 + (lo + hi) / 2) ** 12 - 1) * 100;
}

/** Vad lånet kostar med långivarens exempelränta och avgifter. Okända avgifter räknas som 0
 *  och markeras, så att siffran då är ett golv. */
function cost(p, amount, n) {
  const rate = val(p, "example_rate_percent");
  if (rate == null) return null;
  const setup = val(p, "setup_fee_sek"), avi = val(p, "monthly_fee_sek");
  const monthly = annuity(amount, rate, n) + (avi ?? 0);
  // Går långivarens eget exempel att räkna fram med avgifterna vi hittat, är de rätt avlästa (även
  // en avgift vi inte hittat är då 0). Går det inte, har avgifter eller exempel blandats ihop med ett
  // annat lån på samma sida – siffran är då osäker.
  const chk = exampleCheck(p);
  return { rate, monthly, eff: effective(amount, rate, n, setup ?? 0, avi ?? 0),
    sure: chk ? chk.ok : setup != null && avi != null,
    total: monthly * n + (setup ?? 0) };
}

/** Räknar om långivarens eget exempel. Stämmer det, är avgifterna rätt avlästa. */
function exampleCheck(p) {
  const a = val(p, "example_amount_sek"), n = val(p, "example_term_months"), r = val(p, "example_rate_percent"),
    e = val(p, "example_effective_rate_percent");
  if ([a, n, r, e].some((x) => x == null)) return null;
  const calc = effective(a, r, n, val(p, "setup_fee_sek") ?? 0, val(p, "monthly_fee_sek") ?? 0);
  return { calc, ok: Math.abs(calc - e) <= 0.15 };
}

function quote(b, f) {
  if (!f || !f.quote || f.value == null) return "";
  const src = b.sources[f.source];
  return `<q>${esc(f.quote)}</q>${src ? ` <a href="${src.url}" rel="noopener nofollow" target="_blank">källa</a>` : ""}`;
}

function detail(b, p) {
  const rows = Object.entries(DETAIL).map(([k, label]) => {
    const f = p.fields[k];
    if (!f || f.value == null) return "";
    let v = f.value;
    if (PCT.has(k)) v = pct(v);
    else if (KR.has(k)) v = `${kr.format(v)} kr${k === "monthly_fee_sek" ? "/mån" : ""}`;
    else if (k.startsWith("term_")) v = months(v);
    else if (k === "co_applicant") v = v ? "Ja" : "Nej";
    else if (k === "min_age") v = `${v} år`;
    return `<dt>${label}</dt><dd>${esc(v)} ${quote(b, f)}</dd>`;
  }).join("");
  return `<dl class="terms">${rows}</dl>
    <p class="sources">${b.bank.legal_name && b.bank.legal_name !== b.bank.name ? esc(b.bank.legal_name) + ". " : ""}Senast kontrollerat ${new Date(b.checked_at).toLocaleDateString("sv-SE")}. <a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">Till långivaren</a></p>`;
}

function fees(p) {
  const s = val(p, "setup_fee_sek"), a = val(p, "monthly_fee_sek");
  const f = (v, unit) => v == null ? `<span class="muted">? ${unit}</span>` : v === 0 ? `0 kr ${unit}` : `${kr.format(v)} kr ${unit}`;
  return `${f(s, "uppläggning")}<br>${f(a, "per avi")}`;
}

function example(p) {
  const e = val(p, "example_effective_rate_percent");
  if (e == null) return '<span class="muted">–</span>';
  const a = val(p, "example_amount_sek"), n = val(p, "example_term_months"), r = val(p, "example_rate_percent");
  const chk = exampleCheck(p);
  const tag = !chk ? "" : chk.ok
    ? ` <span class="yn yes" title="Vi har räknat om exemplet med långivarens ränta och avgifter och fått ${pct(chk.calc)}">✓</span>`
    : ` <span class="tag part" title="Vi får ${pct(chk.calc)} med de avgifter vi hittat – någon avgift kan saknas">avviker</span>`;
  return `<b>${pct(e)}</b> effektiv${tag}<br><span class="muted small">${[a != null ? krAmt(a) : null, months(n), r != null ? `ränta ${pct(r)}` : null].filter(Boolean).join(", ")}</span>`;
}

function render() {
  const amount = parseInt(($("#amount").value || "").replace(/\D/g, ""), 10) || 100000;
  const n = +$("#term").value, type = $("#type").value, fits = $("#fits").checked, sortKey = $("#sort").value;
  const items = [];
  for (const b of L.banks) for (const p of b.products || []) {
    if (broker(b, p)) continue;
    if (val(p, "rate_percent") == null && val(p, "example_effective_rate_percent") == null) continue;
    const pt = val(p, "product_type");
    // Standardvyn: lån man kan använda till vad som helst. Lån för ett visst ändamål (solceller,
    // energi, vård …) har ofta lägre ränta men går inte att jämföra – de syns under "Alla".
    if (type === "blanco" ? !["privatlån", "samlingslån"].includes(pt) || EARMARKED.test(p.name) : type && pt !== type) continue;
    if (fits) {
      const lo = val(p, "min_amount_sek"), hi = val(p, "max_amount_sek"), tlo = val(p, "term_min_months"), thi = val(p, "term_max_months");
      if ((lo != null && amount < lo) || (hi != null && amount > hi) || (tlo != null && n < tlo) || (thi != null && n > thi)) continue;
    }
    items.push({ b, p, c: cost(p, amount, n) });
  }
  // Många sparbanker har exakt samma erbjudande – visa det som en rad.
  const groups = new Map();
  for (const it of items) {
    const k = ["name", "rate_percent", "rate_max_percent", "setup_fee_sek", "monthly_fee_sek", "example_rate_percent",
      "example_effective_rate_percent", "example_amount_sek"].map((f) => f === "name" ? it.p.name.toLowerCase() : val(it.p, f)).join("|");
    if (groups.has(k)) groups.get(k).also.push(it.b);
    else groups.set(k, Object.assign(it, { also: [] }));
  }
  items.length = 0;
  items.push(...groups.values());
  const key = { eff: (x) => x.c?.eff, from: (x) => val(x.p, "rate_percent"), ex: (x) => val(x.p, "example_effective_rate_percent") }[sortKey];
  items.sort((x, y) => {
    if (sortKey === "eff" && x.c && y.c && x.c.sure !== y.c.sure) return x.c.sure ? -1 : 1;
    const a = key(x), c = key(y);
    if (a == null && c == null) return x.b.bank.name.localeCompare(y.b.bank.name, "sv");
    if (a == null) return 1;
    if (c == null) return -1;
    return a - c;
  });
  const tb = $("#loans tbody");
  tb.replaceChildren();
  for (const { b, p, c, also } of items) {
    const tr = document.createElement("tr");
    tr.className = "mtg-row";
    const t = val(p, "product_type");
    const status = p.status !== "verifierad" ? ` <span class="tag part" title="${p.status}">?</span>` : "";
    const mine = c
      ? `<b>${kr.format(Math.round(c.monthly))} kr/mån</b><br><span class="muted small">${pct(c.eff)} effektiv${c.sure ? "" : ` <span class="tag part" title="Långivarens exempel går inte att räkna fram med de avgifter vi hittat">osäker</span>`}</span>`
      : val(p, "rate_percent") != null
        ? `<span class="muted small">inget exempel<br>från ${kr.format(Math.round(annuity(amount, val(p, "rate_percent"), n) + (val(p, "monthly_fee_sek") ?? 0)))} kr/mån</span>`
        : '<span class="muted small">inget exempel</span>';
    const lo = val(p, "rate_percent"), hi = val(p, "rate_max_percent");
    const name = also.length ? `${esc(b.bank.name)} <span class="muted small">och ${also.length} till</span>` : esc(b.bank.name);
    tr.innerHTML = `<th scope="row"><button class="expand" aria-expanded="false">${name}</button>${status}<br><span class="muted">${esc(p.name)}${t && !p.name.toLowerCase().includes(t) ? " · " + esc(t) : ""}</span></th>
      <td class="num">${mine}</td>
      <td class="num">${lo == null ? '<span class="muted">–</span>' : hi != null ? `${pct(lo)}–<br>${pct(hi)}` : `från ${pct(lo)}`}</td>
      <td>${fees(p)}</td><td>${example(p)}</td>`;
    const det = document.createElement("tr");
    det.className = "mtg-detail";
    det.hidden = true;
    tr.querySelector(".expand").addEventListener("click", (e) => {
      if (!det.firstChild) det.innerHTML = `<td colspan="5">${also.length ? `<p class="sources">Samma erbjudande hos ${[b, ...also].map((x) => `<a href="${x.bank.homepage}" rel="noopener nofollow" target="_blank">${esc(x.bank.name)}</a>`).join(", ")}.</p>` : ""}${detail(b, p)}</td>`;
      det.hidden = !det.hidden;
      e.currentTarget.setAttribute("aria-expanded", String(!det.hidden));
    });
    tb.append(tr, det);
  }
  $("#note").textContent = `${items.length} erbjudanden. "Ditt lån" räknas med långivarens exempelränta och avgifter för ${kr.format(amount)} kr på ${months(n)}. "osäker" = långivarens eget exempel går inte att räkna fram med avgifterna vi hittat; de lånen sorteras sist. ✓ = vi har räknat om långivarens exempel och fått samma effektiva ränta. ? = inte helt verifierat.`;
}

function renderBrokers() {
  const rows = [];
  for (const b of L.banks) for (const p of b.products || []) {
    if (!broker(b, p)) continue;
    if (val(p, "rate_percent") == null && val(p, "example_effective_rate_percent") == null) continue;
    rows.push({ b, p });
  }
  rows.sort((x, y) => x.b.bank.name.localeCompare(y.b.bank.name, "sv"));
  $("#brokers-panel").hidden = !rows.length;
  const tb = $("#brokers tbody");
  tb.replaceChildren();
  for (const { b, p } of rows) {
    const tr = document.createElement("tr");
    tr.className = "mtg-row";
    const lo = val(p, "rate_percent"), hi = val(p, "rate_max_percent");
    tr.innerHTML = `<th scope="row"><button class="expand" aria-expanded="false">${esc(b.bank.name)}</button><br><span class="muted">${esc(p.name)}</span></th>
      <td class="num">${lo == null ? '<span class="muted">–</span>' : hi != null ? `${pct(lo)}–<br>${pct(hi)}` : `från ${pct(lo)}`}</td>
      <td>${range(val(p, "min_amount_sek"), val(p, "max_amount_sek"), krAmt)}</td><td>${example(p)}</td>`;
    const det = document.createElement("tr");
    det.className = "mtg-detail";
    det.hidden = true;
    tr.querySelector(".expand").addEventListener("click", (e) => {
      if (!det.firstChild) det.innerHTML = `<td colspan="4">${detail(b, p)}</td>`;
      det.hidden = !det.hidden;
      e.currentTarget.setAttribute("aria-expanded", String(!det.hidden));
    });
    tb.append(tr, det);
  }
}

function renderMarket() {
  const c = L.context || {};
  const card = (id, title, src) => c[id] ? `<article class="region"><h2>${title}</h2><div class="hero"><span class="hero-num">${pct(c[id].value)}</span>
    <span class="hero-label">${esc(c[id].name)}${src === "SCB" ? ", " + new Date(c[id].date).toLocaleDateString("sv-SE", { month: "long", year: "numeric" }) : ""}</span>
    <span class="hero-sub">${pp(c[id].chg_1y)} på ett år · ${src}</span></div></article>` : "";
  $("#market").innerHTML = card("se_consumer_new", "Snittränta nya konsumtionslån", "SCB")
    + card("se_consumer_stock", "Alla konsumtionslån", "SCB") + card("se_policy", "Styrräntan", "Riksbanken");
}

function renderMissing() {
  const has = (b) => (b.products || []).some((p) => val(p, "rate_percent") != null || val(p, "example_effective_rate_percent") != null);
  const miss = L.banks.filter((b) => !has(b));
  const el = $("#missing");
  el.hidden = !miss.length;
  el.querySelector("summary").textContent = `${miss.length} långivare kunde inte läsas automatiskt`;
  el.querySelector("ul").innerHTML = miss.map((b) => `<li><a href="${b.bank.homepage}" rel="noopener nofollow" target="_blank">${esc(b.bank.name)}</a></li>`).join("");
}

let timer = null;
fetch("data/personal_loans.json", { cache: "no-cache" }).then((r) => r.json()).then((d) => {
  L = d;
  renderMarket();
  render();
  renderBrokers();
  renderMissing();
  $("#updated").textContent = `Data uppdaterad ${new Date(d.generated_at).toLocaleString("sv-SE", { dateStyle: "long", timeStyle: "short" })}.`;
  $("#amount").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(render, 200); });
  $("#amount").addEventListener("change", () => {
    const v = parseInt($("#amount").value.replace(/\D/g, ""), 10);
    if (v) $("#amount").value = kr.format(v);
  });
  ["#term", "#type", "#sort", "#fits"].forEach((s) => $(s).addEventListener("change", render));
});
