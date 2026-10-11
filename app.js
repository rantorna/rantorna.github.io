"use strict";

const TAX = 0.30; // kapitalinkomstskatt på ränta
const LABELS = {
  product_type: "Kontotyp",
  rate_percent: "Ränta",
  rate_type: "Räntetyp",
  binding_months: "Bindningstid",
  withdrawals: "Uttag",
  free_withdrawals_per_year: "Fria uttag per år",
  withdrawal_terms: "Uttagsregler",
  min_deposit_sek: "Lägsta belopp",
  max_deposit_sek: "Högsta belopp",
  monthly_deposit_cap_sek: "Högst per månad",
  deposit_terms: "Insättning",
  eligibility: "Vem kan öppna",
  requires_other_products: "Kräver andra produkter",
  intro_rate: "Kampanjränta",
  interest_paid: "Räntebetalning",
  guarantee_country: "Insättningsgaranti (land)",
  guarantee_amount: "Garantibelopp",
  rate_valid_from: "Räntan gäller från",
};
const COUNTRY = { SE: "Sverige", LT: "Litauen", NO: "Norge", DK: "Danmark", FI: "Finland", DE: "Tyskland", MT: "Malta", EE: "Estland", LV: "Lettland", NL: "Nederländerna", IE: "Irland", FR: "Frankrike" };

const kr = new Intl.NumberFormat("sv-SE", { maximumFractionDigits: 0 });
const pct = new Intl.NumberFormat("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const $ = (s) => document.querySelector(s);

let DATA = null;

function val(p, k) { return p.fields[k] ? p.fields[k].value : null; }

function fmt(k, v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "boolean") return v ? "Ja" : "Nej";
  switch (k) {
    case "rate_percent": return pct.format(v) + " %";
    case "binding_months": return v === 0 ? "Ingen" : v % 12 === 0 ? `${v / 12} år` : `${v} mån`;
    case "min_deposit_sek": case "max_deposit_sek": return kr.format(v) + " kr";
    case "monthly_deposit_cap_sek": return kr.format(v) + " kr/mån";
    case "guarantee_country": return COUNTRY[v] || v;
    default: return String(v);
  }
}

/** Räntan som gäller för beloppet: belagd trappa först, annars huvudräntan. */
function rateFor(p, amount) {
  const tiers = (p.rate_tiers || []).filter((t) => t.status === "belagt");
  for (const t of tiers) {
    if ((t.min_sek ?? 0) <= amount && (t.max_sek == null || amount <= t.max_sek)) return t.rate_percent;
  }
  return val(p, "rate_percent");
}

/** "1 150 000 kr" -> 1150000. Belopp i euro räknas inte om. */
function guaranteeSek(text) {
  if (!text || !/kr|sek/i.test(text)) return null;
  const n = parseInt(text.replace(/[^\d]/g, ""), 10);
  return n > 10000 ? n : null;
}

/** Tak per månad: schemafältet, annars ur den belagda insättningstexten ("2 000 kr/månad"). */
function monthlyCap(p) {
  const v = val(p, "monthly_deposit_cap_sek");
  if (v != null) return v;
  const f = p.fields.deposit_terms;
  if (!f || f.value == null) return null;
  const m = (f.value + " " + (f.quote || "")).match(/(\d[\d\s]*)\s*(?:kr|kronor)\s*(?:\/|per|i)\s*mån/i);
  return m ? parseInt(m[1].replace(/\s/g, ""), 10) : null;
}

function rows() {
  const out = [];
  for (const b of DATA.banks) {
    for (const p of b.products || []) out.push({ bank: b, p });
  }
  return out;
}

function parseAmount() {
  const n = parseInt($("#amount").value.replace(/\D/g, ""), 10);
  return Number.isFinite(n) ? n : 0;
}

function render() {
  const amount = parseAmount();
  const bind = +document.querySelector('input[name="bind"]:checked').value;
  const f = {
    se: $("#se-guarantee").checked, free: $("#free-wd").checked, noIntro: $("#no-intro").checked,
    noBundle: $("#no-bundle").checked, verified: $("#verified-only").checked, monthly: $("#monthly").checked,
  };
  const q = $("#q").value.trim().toLowerCase();
  const items = rows()
    .map((r) => ({ ...r, rate: rateFor(r.p, amount) }))
    .filter(({ bank, p, rate }) => {
      if (rate == null) return false;
      if (q && !(bank.bank.name + " " + (bank.bank.legal_name || "") + " " + p.name).toLowerCase().includes(q)) return false;
      const bm = val(p, "binding_months");
      if (bind === 0 && bm !== 0 && bm !== null) return false;
      if (bind > 0 && bind < 999 && (bm == null || bm > bind)) return false;
      if (bind === 0 && bm === null && val(p, "product_type") === "fasträntekonto") return false;
      if (f.se && val(p, "guarantee_country") !== "SE") return false;
      if (f.free && val(p, "withdrawals") !== "fria") return false;
      if (f.noIntro && val(p, "intro_rate") === true) return false;
      if (f.noBundle && val(p, "requires_other_products") === true) return false;
      if (f.verified && p.status !== "verifierad") return false;
      const cap = monthlyCap(p);
      if (cap != null && amount > cap && !f.monthly) return false;
      const min = val(p, "min_deposit_sek");
      if (min != null && amount < min) return false;
      return true;
    })
    .sort((a, b) => b.rate - a.rate);

  const list = $("#list");
  list.replaceChildren(...items.map((it) => row(it, amount)));
  $("#empty").hidden = items.length > 0;
  const nBanks = new Set(items.map((i) => i.bank.bank.id)).size;
  $("#summary").textContent = `${items.length} konton hos ${nBanks} banker · avkastning på ${kr.format(amount)} kr under ett år, efter 30 % skatt`;
}

function badge(text, cls) {
  const s = document.createElement("span");
  s.className = "tag " + (cls || "");
  s.textContent = text;
  return s;
}

function row({ bank, p, rate }, amount) {
  const el = $("#row").content.firstElementChild.cloneNode(true);
  el.querySelector(".bank").textContent = bank.bank.name;
  el.querySelector(".product").textContent = p.name;
  const tags = el.querySelector(".tags");
  const statusCls = { "verifierad": "ok", "delvis verifierad": "part", "ej verifierad": "warn" }[p.status];
  tags.append(badge(p.status, statusCls));
  const bm = val(p, "binding_months");
  if (bm) tags.append(badge(fmt("binding_months", bm) + " bindning"));
  const wd = val(p, "withdrawals");
  const WD = { "fria": "fria uttag", "begränsade": "begränsade uttag", "mot avgift": "uttag mot avgift", "ej tillåtna": "låst under bindningstiden" };
  if (WD[wd]) tags.append(badge(WD[wd]));
  const gc = val(p, "guarantee_country");
  if (gc && gc !== "SE") tags.append(badge("garanti: " + (COUNTRY[gc] || gc), "note"));
  if (val(p, "intro_rate")) tags.append(badge("kampanj", "note"));
  const cap = monthlyCap(p);
  if (cap != null) tags.append(badge(`månadsspar max ${kr.format(cap)} kr/mån`, "note"));

  el.querySelector(".rate").textContent = pct.format(rate) + " %";
  const max = val(p, "max_deposit_sek");
  // Månadsspar: genomsnittligt saldo under första året är ca 6,5 månadsinsättningar.
  const base = cap != null ? Math.min(amount, cap * 12) * 6.5 / 12 : max != null ? Math.min(amount, max) : amount;
  const net = base * rate / 100 * (1 - TAX);
  el.querySelector(".yield").textContent = `+${kr.format(net)} kr/år`;

  const dl = el.querySelector(".terms");
  for (const [k, label] of Object.entries(LABELS)) {
    const fld = p.fields[k];
    if (!fld) continue;
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    const shown = fmt(k, fld.value);
    const v = document.createElement("span");
    v.className = "v";
    v.textContent = shown ?? "okänt";
    if (shown == null) v.classList.add("unknown");
    dd.append(v);
    if (shown == null && fld.status !== "okänt") v.title = `Ej belagt: ${fld.status}`;
    if (fld.status === "osäkert") dd.append(" ", badge("osäkert", "part"));
    if (fld.quote && shown != null) {
      const q = document.createElement("q");
      q.textContent = fld.quote;
      const src = bank.sources[fld.source];
      if (src) {
        const a = document.createElement("a");
        a.href = src.url; a.rel = "noopener nofollow"; a.target = "_blank";
        a.textContent = "källa";
        dd.append(q, " ", a);
      } else dd.append(q);
    }
    dl.append(dt, dd);
  }
  const warn = [];
  const gLimit = guaranteeSek(val(p, "guarantee_amount"));
  if (gLimit && amount > gLimit) warn.push(`Beloppet överstiger insättningsgarantin (${kr.format(gLimit)} kr per person och bank enligt banken).`);
  if (max != null && amount > max) warn.push(`Räntan gäller upp till ${kr.format(max)} kr.`);
  for (const fl of p.flags || []) warn.push(fl);
  const srcEl = el.querySelector(".sources");
  srcEl.textContent = (warn.length ? warn.join(" ") + " " : "") + `Senast kontrollerat ${new Date(bank.checked_at).toLocaleDateString("sv-SE")}.`;
  return el;
}

function renderMissing() {
  const miss = DATA.banks.filter((b) => !(b.products || []).some((p) => val(p, "rate_percent") != null));
  const el = $("#missing");
  el.hidden = miss.length === 0;
  el.querySelector("summary").textContent = `${miss.length} banker kunde inte läsas automatiskt`;
  el.querySelector("ul").replaceChildren(...miss.sort((a, b) => a.bank.name.localeCompare(b.bank.name, "sv")).map((b) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = b.bank.homepage; a.rel = "noopener nofollow"; a.target = "_blank";
    a.textContent = b.bank.name;
    li.append(a);
    return li;
  }));
}

function bindFilters() {
  $("#filters").addEventListener("input", (e) => {
    if (e.target.id === "amount") {
      const n = parseAmount();
      e.target.value = n ? kr.format(n) : "";
    }
    render();
  });
}

fetch("data/rates.json", { cache: "no-cache" })
  .then((r) => r.json())
  .then((d) => {
    DATA = d;
    $("#updated").textContent = `Data uppdaterad ${new Date(d.generated_at).toLocaleString("sv-SE", { dateStyle: "long", timeStyle: "short" })}.`;
    bindFilters();
    render();
    renderMissing();
  })
  .catch(() => { $("#summary").textContent = "Kunde inte läsa in räntorna."; });
