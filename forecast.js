"use strict";
// Riksbankens räntebana och marknadens förväntningar, med tolkning för valet mellan rörligt och bundet.
// Kräver charts.js. renderForecast(root, macroJson, { full: true })

(() => {
  const f2 = (v) => v.toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const quarter = (d) => `kvartal ${Math.floor((+d.slice(5, 7) - 1) / 3) + 1} ${d.slice(0, 4)}`;
  const longDate = (d) => new Date(d + "T12:00:00").toLocaleDateString("sv-SE", { day: "numeric", month: "long", year: "numeric" });

  /** Genomsnitt av banan för perioden från i dag och `years` år framåt (kvartalsvärden). */
  function avgAhead(obs, years) {
    const today = new Date().toISOString().slice(0, 10);
    const end = new Date(Date.now() + years * 365.25 * 864e5).toISOString().slice(0, 10);
    const v = obs.filter(([d]) => d > today && d <= end).map(([, x]) => x);
    // Banan måste räcka nästan hela perioden, annars blir snittet för en kortare period.
    const reach = new Date(Date.now() + years * 0.9 * 365.25 * 864e5).toISOString().slice(0, 10);
    if (!obs.length || obs.at(-1)[0] < reach) return null;
    return v.length ? { avg: v.reduce((a, b) => a + b, 0) / v.length, until: obs.filter(([d]) => d <= end).at(-1)[0] } : null;
  }

  function interpret(F, S) {
    const pol = S.se_policy?.latest.value, rorlig = S.se_mtg_new_var?.latest;
    if (pol == null || !rorlig) return "";
    const margin = rorlig.value - pol;
    const rows = [[2, "se_mtg_new_1y2y", "1–2 år"], [3, "se_mtg_new_2y3y", "2–3 år"], [5, "se_mtg_new_3y5y", "3–5 år"]].map(([y, id, label]) => {
      const a = avgAhead(F.policy.obs, y), m = avgAhead(F.market.obs, y), fixed = S[id]?.latest.value;
      if (!a || fixed == null) return "";
      const exp = a.avg + margin, mexp = m ? m.avg + margin : null;
      return `<tr><th scope="row">${y} år</th><td class="num">${f2(exp)} %</td><td class="num">${mexp != null ? f2(mexp) + " %" : "–"}</td>
        <td class="num">${f2(fixed)} %<br><span class="muted small">snitt bundet ${label}</span></td></tr>`;
    }).join("");
    const month = new Date(rorlig.date).toLocaleDateString("sv-SE", { month: "long", year: "numeric" });
    const p3 = avgAhead(F.policy.obs, 3), m3 = avgAhead(F.market.obs, 3), fixed3 = S.se_mtg_new_2y3y?.latest.value;
    let verdict = "";
    if (p3 && fixed3 != null) {
      const exp = p3.avg + margin, d = fixed3 - exp;
      verdict = Math.abs(d) < 0.15
        ? `Om Riksbankens bana slår in kostar rörligt och bundet ungefär lika mycket de närmaste tre åren. Då betalar du i praktiken inget extra för att låsa räntan.`
        : d > 0
          ? `Om Riksbankens bana slår in blir rörligt ungefär ${f2(d)} procentenheter billigare per år än bundet 2–3 år. Bindningen kostar alltså något – det du betalar för är att slippa överraskningar om räntan stiger mer än Riksbanken tror.`
          : `Om Riksbankens bana slår in blir bundet 2–3 år ungefär ${f2(-d)} procentenheter billigare per år än rörligt. Då betalar du alltså mindre för att låsa räntan än vad rörligt väntas kosta.`;
    }
    const gap = p3 && m3 ? m3.avg - p3.avg : null;
    const marketLine = gap == null ? "" : Math.abs(gap) < 0.1
      ? `Marknaden räknade med ungefär samma utveckling som Riksbanken.`
      : `Marknaden räknade med en <b>${gap > 0 ? "högre" : "lägre"}</b> styrränta än Riksbanken – i snitt ${f2(Math.abs(gap))} procentenheter de kommande tre åren. Bundna räntor sätts efter marknadens förväntningar, så de speglar marknadens bild snarare än Riksbankens.`;
    return `<div class="fc-text">
      <h3>Rörligt eller bundet?</h3>
      <p>Den rörliga bolåneräntan följer styrräntan. I ${month} låg snitträntan för nya rörliga bolån på ${f2(rorlig.value)} %, alltså ${f2(margin)} procentenheter över styrräntan. Lägger man samma påslag på räntebanan får man en uppskattning av vad rörligt kostar framöver – som kan jämföras med vad det kostar att binda i dag:</p>
      <div class="table-scroll"><table class="mtg fc-table">
        <thead><tr><th scope="col">Period</th><th scope="col" class="num">Rörligt enligt Riksbankens bana</th><th scope="col" class="num">Rörligt enligt marknaden</th><th scope="col" class="num">Bundet i dag</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <p>${verdict} ${marketLine}</p>
      <h3>Så kan du tolka det</h3>
      <ul>
        <li><b>Räntebanan är en prognos, inte ett löfte.</b> Riksbanken ändrar den vid varje rapport, och den har ofta slagit fel när ekonomin tagit en oväntad vändning – som när inflationen steg 2022 och styrräntan gick från 0 till 4 % på ett och ett halvt år.</li>
        <li><b>Rörligt har oftast blivit billigare över tid,</b> eftersom den som binder betalar för tryggheten. Men inte alltid: den som band före 2022 vann stort.</li>
        <li><b>Den viktigaste frågan är din egen marginal.</b> Klarar din ekonomi att räntan blir 2–3 procentenheter högre än i dag? Om inte, är förutsägbarheten värd mer än den förväntade besparingen. Många delar därför lånet på flera bindningstider.</li>
        <li><b>Jämför bankernas räntor, inte bara bindningstiden.</b> Skillnaden mellan långivare är ofta större än skillnaden mellan rörligt och bundet – se tabellen ovan.</li>
      </ul>
      <p class="sub">Uppskattningen förutsätter att påslaget mellan styrränta och bolåneränta är oförändrat. Bundna snitträntor från SCB (nya avtal, ${month}). Ingen rådgivning.</p>
    </div>`;
  }

  window.renderForecast = (root, macro, { full = false, cutoffYears = 3 } = {}) => {
    const F = macro.forecast, S = macro.series;
    if (!root || !F || !S.se_policy) { if (root) root.hidden = true; return; }
    const since = new Date(Date.now() - cutoffYears * 365.25 * 864e5).toISOString().slice(0, 10);
    const hist = S.se_policy.obs.filter(([d]) => d >= since);
    const join = (obs) => [hist.at(-1), ...obs.filter(([d]) => d > hist.at(-1)[0])];
    const series = [
      { label: "Styrräntan", color: "var(--series-1)", points: hist },
      { label: `Riksbankens räntebana (${F.policy.round})`, color: "var(--series-1)", dash: true, points: join(F.policy.obs) },
      { label: "Marknadens förväntningar", color: "var(--series-2)", dash: true, points: join(F.market.obs) },
      { label: `Förra räntebanan (${F.policy_prev.round})`, color: "var(--muted)", dash: true, points: join(F.policy_prev.obs) },
    ];
    const p = F.policy.obs, peak = p.reduce((a, b) => (b[1] > a[1] ? b : a));
    const now = S.se_policy.latest.value;
    const dir = peak[1] - now > 0.1 ? `höjs till omkring ${f2(peak[1])} % (${quarter(peak[0])})` : p.at(-1)[1] < now - 0.1 ? `sänks till omkring ${f2(p.at(-1)[1])} %` : `ligger kvar kring ${f2(now)} %`;
    root.innerHTML = `
      <p class="fc-lead">I den senaste penningpolitiska rapporten (${longDate(F.policy.published)}) räknar Riksbanken med att styrräntan <b>${dir}</b>. Styrräntan är i dag ${f2(now)} %.</p>
      <div class="legend" id="fc-legend"></div>
      <div class="chart" id="fc-chart"></div>
      <p class="sub">Kvartalsgenomsnitt. Marknadens förväntningar enligt terminsprissättningen när rapporten gjordes. Källa: <a href="${F.source_url}" rel="noopener" target="_blank">Riksbanken</a>. Ny rapport kommer fyra gånger om året och hämtas automatiskt.</p>
      ${full ? interpret(F, S) : `<p><a href="bolan.html#rantebana">Vad betyder räntebanan för valet mellan rörligt och bundet bolån?</a></p>`}`;
    legend(root.querySelector("#fc-legend"), series);
    const draw = () => lineChart(root.querySelector("#fc-chart"), series);
    draw();
    let t;
    addEventListener("resize", () => { clearTimeout(t); t = setTimeout(draw, 150); });
  };
})();
