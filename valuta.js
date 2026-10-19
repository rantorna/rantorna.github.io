"use strict";
// Fliken Valuta: kortkostnad utomlands, test av dynamisk valutaomräkning och kronan i perspektiv.

let X = null;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const kr0 = new Intl.NumberFormat("sv-SE", { maximumFractionDigits: 0 });
const num = (v, d = 2) => v.toLocaleString("sv-SE", { minimumFractionDigits: d, maximumFractionDigits: d });
const parse = (s) => parseFloat(String(s || "").replace(/\s/g, "").replace(",", ".")) || 0;
const sekPer = (cur) => X.latest[cur];                 // kronor per enhet
const rateTxt = (cur) => sekPer(cur) < 0.1 ? num(sekPer(cur) * 100, 2) + ` kr per 100 ${cur}` : num(sekPer(cur), 4) + ` kr per ${cur}`;
const day = (d) => new Date(d + "T12:00:00").toLocaleDateString("sv-SE", { day: "numeric", month: "long", year: "numeric" });

function currencyOptions(sel, def = "EUR") {
  const order = ["EUR", "USD", "GBP", "NOK", "DKK"];
  const rest = Object.keys(X.names).filter((c) => !order.includes(c)).sort((a, b) => X.names[a].localeCompare(X.names[b], "sv"));
  sel.innerHTML = [...order, ...rest].filter((c) => X.latest[c]).map((c) => `<option value="${c}"${c === def ? " selected" : ""}>${c} – ${esc(X.names[c])}</option>`).join("");
}

/* ---------- Kortet utomlands ---------- */

function renderCards() {
  const cur = $("#c-cur").value, amount = parse($("#c-amount").value) || 1000;
  $("#c-unit").textContent = cur;
  const base = amount * sekPer(cur);
  $("#c-ref").innerHTML = `${kr0.format(amount)} ${cur} är <b>${kr0.format(Math.round(base))} kr</b> till ECB:s referenskurs (${rateTxt(cur)}, ${day(X.date)}). Det är priset utan något påslag.`;
  const rows = X.cards.map((c) => {
    const pay = c.fx == null ? null : base * (1 + c.fx / 100);
    const atm = pay == null || (c.atm_pct == null && c.atm_min == null) ? null
      : pay + Math.max(c.atm_min || 0, base * (c.atm_pct || 0) / 100);
    return { ...c, pay, atm };
  }).sort((a, b) => (a.pay == null) - (b.pay == null) || a.pay - b.pay || a.issuer.localeCompare(b.issuer, "sv"));
  const muted = '<span class="muted">–</span>';
  $("#fxcards tbody").innerHTML = rows.map((c) => `<tr>
      <th scope="row">${esc(c.issuer)}${c.also ? ` <span class="muted small">och ${c.also} till</span>` : ""}${c.verified ? "" : ' <span class="tag part" title="inte helt verifierat">?</span>'}<br><span class="muted">${esc(c.card)}</span></th>
      <td class="num">${c.pay == null ? muted : `<b>${kr0.format(Math.round(c.pay))} kr</b><br><span class="muted small">+${kr0.format(Math.round(c.pay - base))} kr</span>`}</td>
      <td class="num">${c.atm == null ? muted : `${kr0.format(Math.round(c.atm))} kr<br><span class="muted small">+${kr0.format(Math.round(c.atm - base))} kr</span>`}</td>
      <td class="num">${c.fx == null ? '<span class="muted small">okänt</span>' : num(c.fx) + " %"}</td></tr>`).join("");
  $("#c-note").textContent = `${rows.length} kort. "Betala med kortet" = referenskursen plus kortets valutapåslag. "Ta ut kontanter" lägger till uttagsavgiften (procent eller lägsta avgift, det som blir högst). Visa och Mastercard använder sina egna dagskurser, som kan avvika något från ECB:s. Årsavgifter ingår inte – se Lån & kort för kortens totala kostnad.`;
}

/* ---------- Betala i SEK? ---------- */

function renderDcc() {
  const cur = $("#d-cur").value, amount = parse($("#d-amount").value), sek = parse($("#d-sek").value);
  $("#d-unit").textContent = cur;
  const res = $("#d-result");
  if (!amount) { res.innerHTML = ""; return; }
  const base = amount * sekPer(cur);
  const pick = $("#d-card").value, card = pick === "" ? null : X.cards[+pick];
  const fx = card?.fx ?? medianFx();
  const local = base * (1 + fx / 100);
  const cardTxt = card ? `med ${esc(card.issuer)} ${esc(card.card)} (påslag ${num(fx)} %)` : `med ett kort med ${num(fx)} % påslag (mittenvärdet bland korten i jämförelsen)`;
  let html = `<p>${num(amount)} ${cur} är ${num(base)} kr till dagens referenskurs. Betalar du i <b>${cur}</b> ${cardTxt} blir det ungefär <b>${kr0.format(Math.round(local))} kr</b>.</p>`;
  if (sek) {
    const markup = (sek / base - 1) * 100, extra = sek - local;
    const verdict = extra > 0.5
      ? `<p class="verdict bad"><b>Välj ${cur}.</b> Terminalens kronpris har ett påslag på ${num(markup, 1)} % mot referenskursen och kostar ungefär <b>${kr0.format(Math.round(extra))} kr mer</b> än att betala i ${cur}.</p>`
      : `<p class="verdict ok"><b>Terminalens kronpris är rimligt.</b> Påslaget är ${num(markup, 1)} % mot referenskursen – ungefär som eller lägre än ditt korts påslag. Skillnaden är ${kr0.format(Math.round(Math.abs(extra)))} kr.</p>`;
    html = verdict + html;
  } else {
    html += `<p class="muted small">Fyll i kronbeloppet som terminalen visar för att se vad butikens kurs kostar.</p>`;
  }
  res.innerHTML = html;
}

function medianFx() {
  const v = X.cards.map((c) => c.fx).filter((x) => x != null).sort((a, b) => a - b);
  return v.length ? v[Math.floor(v.length / 2)] : 1.65;
}

/* ---------- Kronan ---------- */

function renderKrona() {
  const card = (title, value, label, chg, note) => `<article class="region"><h2>${title}</h2><div class="hero">
    <span class="hero-num">${value}</span><span class="hero-label">${label}</span>
    <span class="hero-sub">${chg}</span>${note ? `<span class="hero-sub">${note}</span>` : ""}</div></article>`;
  const ch = (v) => v == null ? "" : `${v > 0 ? "+" : "−"}${num(Math.abs(v), 1)} % på ett år – kronan har ${v > 0 ? "försvagats" : "stärkts"}`;
  $("#k-market").innerHTML =
    card("Euro", num(X.latest.EUR, 2) + " kr", `per euro, ${day(X.date)}`, ch(X.change_1y.EUR)) +
    card("Dollar", num(X.latest.USD, 2) + " kr", `per dollar, ${day(X.date)}`, ch(X.change_1y.USD)) +
    (X.kix ? card("KIX-index", num(X.kix.latest[1], 1), "kronan mot handelspartnernas valutor", ch(X.kix.change_1y), "Högre = svagare krona") : "");
  renderKronaChart();
  renderRateChart();
  renderExplain();
}

function renderKronaChart() {
  const years = +document.querySelector('input[name="krange"]:checked').value;
  const since = new Date(Date.now() - Math.min(years, 10) * 365.25 * 864e5).toISOString().slice(0, 10);
  const series = [
    { label: "Kronor per euro", color: "var(--series-1)", points: X.history.EUR.filter(([d]) => d >= since) },
    { label: "Kronor per dollar", color: "var(--series-2)", points: X.history.USD.filter(([d]) => d >= since) },
  ];
  legend($("#k-legend"), series);
  lineChart($("#k-chart"), series, { fmt: (v) => num(v, 2) + " kr", axis: (v) => num(v, 1), zero: false });
}

function renderRateChart() {
  const R = X.rates || {};
  const series = [
    { label: "Sverige minus euroområdet", color: "var(--series-1)", points: R.diff_se_eu_2y || [] },
    { label: "Sverige minus USA", color: "var(--series-2)", points: R.diff_se_us_2y || [] },
  ];
  legend($("#r-legend"), series);
  lineChart($("#r-chart"), series, { fmt: (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + num(Math.abs(v), 2) + " pe", axis: (v) => num(v, 1) });
}

function renderExplain() {
  const L = (X.rates || {}).latest || {};
  if (L.se_gvb2y == null || L.eu_y2y == null) { $("#k-explain").innerHTML = ""; return; }
  const dEu = L.se_gvb2y - L.eu_y2y, dUs = L.us_t2y != null ? L.se_gvb2y - L.us_t2y : null;
  const cmp = (d) => Math.abs(d) < 0.1 ? "ungefär lika hög" : `${num(Math.abs(d))} procentenheter ${d > 0 ? "högre" : "lägre"}`;
  // Terminskurs ett år fram enligt räntepariteten, med 3-månadersräntorna som ungefärliga korta räntor.
  let fwd = "";
  if (L.se_tb3m != null && L.eu_y3m != null) {
    const f = X.latest.EUR * (1 + L.se_tb3m / 100) / (1 + L.eu_y3m / 100), diff = f - X.latest.EUR;
    fwd = `<li><b>Terminskursen följer räntorna, inte förväntningarna.</b> Den som i dag låser eurokursen ett år framåt får ungefär <b>${num(f, 2)} kr</b> per euro – ${num(Math.abs(diff) * 100, 0)} öre ${diff < 0 ? "mindre" : "mer"} än i dag. Det är ingen prognos: skillnaden motsvarar ränteskillnaden – det man avstår från eller vinner på att ha pengarna i kronor i stället för euro under året (svenska korta räntor ${num(L.se_tb3m)} %, euroområdets ${num(L.eu_y3m)} %).</li>`;
  }
  $("#k-explain").innerHTML = `
    <h3>Så påverkar räntor och valuta varandra</h3>
    <ul>
      <li><b>Räntedifferensen drar kapital.</b> I dag är räntan på svenska 2-åriga statsobligationer ${num(L.se_gvb2y)} %, ${cmp(dEu)} än i euroområdet${dUs != null ? ` och ${cmp(dUs)} än i USA` : ""}. När svenska räntor är lägre blir det mindre lockande att placera i kronor, och det brukar tynga kronan. Stiger de svenska räntorna mer än omvärldens – till exempel om Riksbanken höjer mer än ECB – brukar kronan stärkas. Sambandet är löst: oro i världen försvagar ofta kronan oavsett räntorna, eftersom investerare då söker sig till större valutor.</li>
      ${fwd}
      <li><b>Kronan påverkar inflationen – och därmed räntan.</b> En svag krona gör importerade varor dyrare och höjer inflationen. Det kan få Riksbanken att hålla räntan högre. En stark krona dämpar inflationen och ger utrymme för lägre ränta. Därför följer Riksbanken kronan noga. Se <a href="bolan.html#rantebana">Riksbankens räntebana</a> och <a href="rantelaget.html">Ränteläget</a>.</li>
      <li><b>För dig:</b> en svagare krona gör utlandsresan och importerade varor dyrare, men ger mer i kronor för utländska aktier och fonder. Valutan går inte att förutse – den som ska växla stora belopp kan sprida växlingen över tid.</li>
    </ul>
    <p class="sub">Räntorna är 2-åriga statsobligationer (euroområdet: AAA-stater). Terminskursen är räknad med statsskuldväxlar på 3 månader som ungefärliga korta räntor; bankernas terminskurser har dessutom ett påslag.</p>`;
}

/* ---------- Gemensamt ---------- */

function showView() {
  const v = document.querySelector('input[name="view"]:checked').value;
  for (const k of ["card", "dcc", "krona"]) $("#v-" + k).hidden = v !== k;
  history.replaceState(null, "", v === "card" ? location.pathname : "#" + v);
  if (v === "krona") renderKrona();
}

fetch("data/fx.json", { cache: "no-cache" }).then((r) => r.json()).then((d) => {
  X = d;
  currencyOptions($("#c-cur"));
  currencyOptions($("#d-cur"));
  $("#d-card").innerHTML = `<option value="">Vet inte / annat kort</option>` +
    X.cards.map((c, i) => c.fx == null ? "" : `<option value="${i}">${esc(c.issuer)} – ${esc(c.card)} (${num(c.fx)} %)</option>`).join("");
  const h = location.hash.slice(1);
  if (["dcc", "krona"].includes(h)) document.querySelector(`input[name="view"][value="${h}"]`).checked = true;
  renderCards();
  renderDcc();
  showView();
  $("#updated").textContent = `Data uppdaterad ${new Date(X.generated_at).toLocaleString("sv-SE", { dateStyle: "long", timeStyle: "short" })}. Kurser från ECB ${day(X.date)}.`;
  $("#sources").innerHTML = `Källor: <a href="${X.source_url}" rel="noopener" target="_blank">ECB:s referenskurser</a>, Riksbankens KIX-index, räntor från <a href="rantelaget.html">Ränteläget</a> och kortens valutapåslag från <a href="lan.html#kort">kreditkortsjämförelsen</a>.`;
  document.querySelectorAll('input[name="view"]').forEach((i) => i.addEventListener("change", showView));
  document.querySelectorAll('input[name="krange"]').forEach((i) => i.addEventListener("change", renderKronaChart));
  let t;
  const later = (fn) => () => { clearTimeout(t); t = setTimeout(fn, 200); };
  $("#c-amount").addEventListener("input", later(renderCards));
  $("#c-cur").addEventListener("change", renderCards);
  ["#d-amount", "#d-sek"].forEach((s) => $(s).addEventListener("input", later(renderDcc)));
  ["#d-cur", "#d-card"].forEach((s) => $(s).addEventListener("change", renderDcc));
  addEventListener("resize", later(() => { if (!$("#v-krona").hidden) { renderKronaChart(); renderRateChart(); } }));
});
