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
  age_min: "Lägsta ålder",
  age_max: "Högsta ålder",
  age_terms: "Vid åldersgränsen",
  who_can_open: "Vem kan öppna och sätta in",
};
const COUNTRY = { SE: "Sverige", LT: "Litauen", NO: "Norge", DK: "Danmark", FI: "Finland", DE: "Tyskland", MT: "Malta", EE: "Estland", LV: "Lettland", NL: "Nederländerna", IE: "Irland", FR: "Frankrike" };

const kr = new Intl.NumberFormat("sv-SE", { maximumFractionDigits: 0 });
const pct = new Intl.NumberFormat("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const $ = (s) => document.querySelector(s);

let DATA = null, YOUTH = null;
const who = () => document.querySelector('input[name="who"]:checked')?.value || "vuxen";
const PAGE = 50;
let showAll = false;

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
  const w = who(), out = [];
  if (w === "vuxen") {
    for (const b of DATA.banks) for (const p of b.products || []) out.push({ bank: b, p });
  } else {
    // Barn: barnkonton och vanliga konton som banken säger kan öppnas i barnets namn. Unga: ungdomskonton.
    for (const b of (YOUTH || { banks: [] }).banks) for (const p of b.products || []) {
      // Saknas eller är målgruppen tvetydig avgör namnet ("Ungdomskonto" hör till Unga).
      const tg = val(p, "target_group"), young = /ung/i.test(p.name);
      if (w === "ungdom" ? tg === "ungdom" || young : tg === "barn" || (tg == null && !young)) out.push({ bank: b, p });
    }
  }
  return out;
}

/** Barn- och ungdomskontona laddas först när någon väljer dem. */
function ensureYouth() {
  if (who() === "vuxen" || YOUTH) return Promise.resolve();
  return fetch("data/youth.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : { banks: [] })
    .catch(() => ({ banks: [] })).then((d) => { YOUTH = d; });
}

function renderYouthNote() {
  const w = who(), el = $("#youth-note");
  el.hidden = w === "vuxen";
  if (w === "barn") el.innerHTML = "<b>Sparande i barnets namn.</b> Här finns särskilda barnsparkonton och vanliga sparkonton som banken skriver att man kan öppna åt ett barn. De flesta storbanker har inget eget barnkonto, och många nischbanker kräver att kontohavaren är 18 år – de syns därför inte här. Räntan beskattas med 30 %, precis som för vuxna.";
  if (w === "ungdom") el.innerHTML = "<b>Konton för unga.</b> Ungdomskonton har en åldersgräns, och räntan eller villkoren ändras ofta när den gränsen passeras – se villkoren under varje konto. Från 18 år kan du också öppna de flesta vanliga sparkonton.";
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
  // Bara de första raderna ritas direkt – resten på begäran. Håller filtreringen snabb även på långsamma datorer.
  const shown = showAll ? items : items.slice(0, PAGE);
  list.replaceChildren(...shown.map((it) => row(it, amount)));
  const more = $("#more");
  more.hidden = items.length <= shown.length;
  more.textContent = `Visa alla ${items.length} konton`;
  $("#empty").hidden = items.length > 0;
  const nBanks = new Set(items.map((i) => i.bank.bank.id)).size;
  const ctx = DATA.context || {};
  const infl = ctx.kpif != null ? ` · "real" = efter skatt och ${String(ctx.kpif).replace(".", ",")} % inflation (KPIF, ${new Date(ctx.kpif_month).toLocaleDateString("sv-SE", { month: "long", year: "numeric" })})` : "";
  $("#summary").textContent = `${items.length} konton hos ${nBanks} banker · avkastning på ${kr.format(amount)} kr under ett år, efter 30 % skatt${infl}`;
  renderIsk(amount);
  if (who() === "vuxen") renderBench(items, amount); else $("#bench").hidden = true;
  renderYouthNote();
  $("#missing").hidden = who() !== "vuxen" || !$("#missing ul").children.length;
}

/** Riktmärke: vad pengarna i banken i snitt ger enligt SCB, mot det bästa kontot utan bindning här. */
function renderBench(items, amount) {
  const ctx = DATA.context || {}, el = $("#bench");
  if (!el || ctx.dep_hh_free == null) return;
  const free = items.filter((i) => val(i.p, "binding_months") === 0 && val(i.p, "withdrawals") === "fria" && val(i.p, "intro_rate") !== true)
    .map((i) => i.rate);
  const best = free.length ? Math.max(...free) : null;
  const f = (v) => String(Math.round(v * 100) / 100).replace(".", ",");
  const month = new Date(ctx.dep_month).toLocaleDateString("sv-SE", { month: "long", year: "numeric" });
  el.hidden = false;
  el.innerHTML = `<b>Snittet i bankerna:</b> på konton utan villkor fick hushållen i genomsnitt ${f(ctx.dep_hh_free)} % i ${month}, `
    + `och ${f(ctx.dep_hh_all)} % på alla pengar i banken (SCB).`
    + (best != null ? ` Det bästa kontot med fria uttag här ger ${f(best)} % – på ${kr.format(amount)} kr är skillnaden ${kr.format(Math.round((best - ctx.dep_hh_free) / 100 * amount * (1 - TAX)))} kr om året efter skatt.` : "");
}

/** Påminnelse om ISK: under grundnivån är sparandet skattefritt – det ändrar jämförelsen. */
function renderIsk(amount) {
  const ctx = DATA.context || {}, el = $("#isk-note");
  if (!el || ctx.isk_grund == null) return;
  el.hidden = false;
  const g = kr.format(ctx.isk_grund), sch = String(ctx.isk_schablon).replace(".", ",");
  el.innerHTML = `<b>Tänk på ISK.</b> ${ctx.isk_year} är sparande på ISK, kapitalförsäkring och PEPP skattefritt upp till ${g} kr sammanlagt, `
    + `och ränta på kontanter på ett ISK beskattas inte om räntan är högst ${sch} % (schablonräntan). `
    + (amount <= ctx.isk_grund ? `Med ${kr.format(amount)} kr kan alltså en lägre ränta på ett ISK ge mer än ett sparkonto efter skatt – om banken erbjuder ränta på ISK och du inte redan använder grundnivån.` : `Över grundnivån beskattas ISK med ${String(ctx.isk_skatt).replace(".", ",")} % av kapitalet per år.`)
    + ` <a href="rantelaget.html">Mer om skatteräntorna</a>.`;
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
  const tg = val(p, "target_group");
  if (tg) {
    const a0 = val(p, "age_min"), a1 = val(p, "age_max");
    const ages = a0 != null && a1 != null ? ` ${a0}–${a1} år` : a1 != null ? ` till ${a1} år` : a0 != null ? ` från ${a0} år` : "";
    tags.append(badge(val(p, "youth_only") !== true ? "vanligt konto, kan öppnas för barn" : (/ung/i.test(p.name) || tg === "ungdom" ? "ungdomskonto" : "barnkonto") + ages, "note"));
  }
  const cap = monthlyCap(p);
  if (cap != null) tags.append(badge(`månadsspar max ${kr.format(cap)} kr/mån`, "note"));

  el.querySelector(".rate").textContent = pct.format(rate) + " %";
  const max = val(p, "max_deposit_sek");
  // Månadsspar: genomsnittligt saldo under första året är ca 6,5 månadsinsättningar.
  const base = cap != null ? Math.min(amount, cap * 12) * 6.5 / 12 : max != null ? Math.min(amount, max) : amount;
  const net = base * rate / 100 * (1 - TAX);
  const ctx = DATA.context || {};
  const yieldEl = el.querySelector(".yield");
  yieldEl.textContent = `+${kr.format(net)} kr/år`;
  if (ctx.kpif != null) {
    // Real avkastning: efter skatt minus vad inflationen äter upp av hela beloppet.
    const real = net - base * ctx.kpif / 100;
    const r = document.createElement("span");
    r.className = "real";
    r.textContent = `${real >= 0 ? "+" : "−"}${kr.format(Math.abs(real))} kr real`;
    r.title = `Efter 30 % skatt och ${String(ctx.kpif).replace(".", ",")} % inflation (KPIF)`;
    yieldEl.append(document.createElement("br"), r);
  }

  // Villkor och citat byggs först när raden fälls ut – annars blir varje filtrering tung.
  const details = el.querySelector("details");
  details.addEventListener("toggle", () => {
    if (details.open && !details.dataset.built) {
      fillTerms(el.querySelector(".terms"), bank, p);
      details.dataset.built = "1";
    }
  });
  const warn = [];
  const gLimit = guaranteeSek(val(p, "guarantee_amount"));
  if (gLimit && amount > gLimit) warn.push(`Beloppet överstiger insättningsgarantin (${kr.format(gLimit)} kr per person och bank enligt banken).`);
  if (max != null && amount > max) warn.push(`Räntan gäller upp till ${kr.format(max)} kr.`);
  for (const fl of p.flags || []) warn.push(fl);
  const srcEl = el.querySelector(".sources");
  srcEl.textContent = (warn.length ? warn.join(" ") + " " : "") + `Senast kontrollerat ${new Date(bank.checked_at).toLocaleDateString("sv-SE")}.`;
  return el;
}

function fillTerms(dl, bank, p) {
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

let renderTimer;
function bindFilters() {
  $("#filters").addEventListener("submit", (e) => e.preventDefault());
  $("#more").addEventListener("click", () => { showAll = true; render(); });
  $("#filters").addEventListener("input", (e) => {
    showAll = false;
    if (e.target.id === "amount") {
      const n = parseAmount();
      e.target.value = n ? kr.format(n) : "";
      // vänta tills man slutat skriva
      clearTimeout(renderTimer);
      renderTimer = setTimeout(render, 200);
      return;
    }
    if (e.target.name === "who") { ensureYouth().then(render); return; }
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
