"use strict";
// Senaste ränteändringar ur data/changes.json. Används av flera sidor:
//   renderChanges("#changes", ["savings"])

(() => {
  const SIGN = { up: "▲", down: "▼" };
  const e = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, field) => field.endsWith("_sek")
    ? `${v.toLocaleString("sv-SE")} kr`
    : `${v.toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %`;
  // Bestämd form i löptexten: "sänkte räntan på …"
  const DEF = { "ränta": "räntan", "listränta": "listräntan", "snittränta": "snitträntan", "lägsta ränta": "lägsta räntan",
    "årsavgift": "årsavgiften", "valutapåslag": "valutapåslaget", "återbäringsränta": "återbäringsräntan" };
  const day = (d) => new Date(d + "T12:00:00").toLocaleDateString("sv-SE", { day: "numeric", month: "short" });

  /** Samma ändring hos flera banker samma dag (sparbankerna följer Swedbank) blir en rad. */
  function group(entries) {
    const g = new Map();
    for (const x of entries) {
      const k = [x.date, x.segment, x.product.toLowerCase(), x.field, x.old, x.new].join("|");
      if (g.has(k)) g.get(k).banks.push(x.bank);
      else g.set(k, { ...x, banks: [x.bank] });
    }
    return [...g.values()];
  }

  function row(x) {
    x.banks.sort((a, b) => a.localeCompare(b, "sv"));
    const dir = x.new > x.old ? "up" : "down";
    // För sparräntor är en höjning bra, för låneräntor och avgifter dålig – färgen säger inget, pilen och ordet gör det.
    const verb = dir === "up" ? "höjde" : "sänkte";
    const banks = x.banks.length > 1 ? `${e(x.banks[0])} och ${x.banks.length - 1} till` : e(x.banks[0]);
    const all = x.banks.length > 1 ? ` title="${e(x.banks.join(", "))}"` : "";
    return `<li><span class="chg-date">${day(x.date)}</span>
      <span class="chg-text"><b${all}>${banks}</b> ${verb} ${e(DEF[x.label] || x.label)} på <i>${e(x.product)}</i></span>
      <span class="chg-val">${fmt(x.old, x.field)} → <b>${fmt(x.new, x.field)}</b> <span aria-hidden="true">${SIGN[dir]}</span></span></li>`;
  }

  window.renderChanges = (target, segments, { days = 60, show = 12 } = {}) => {
    const root = document.querySelector(target);
    if (!root) return;
    fetch("data/changes.json", { cache: "no-cache" }).then((r) => r.ok ? r.json() : []).catch(() => []).then((log) => {
      const since = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
      const items = group(log.filter((x) => segments.includes(x.segment) && x.date >= since));
      if (!items.length) {
        root.innerHTML = `<p class="sub">Inga ändrade räntor de senaste ${days} dagarna.</p>`;
        return;
      }
      const list = (n) => items.slice(0, n).map(row).join("");
      root.innerHTML = `<ol class="chg-list">${list(show)}</ol>` +
        (items.length > show ? `<button class="more" type="button">Visa alla ${items.length} ändringar</button>` : "");
      root.querySelector(".more")?.addEventListener("click", (ev) => {
        root.querySelector(".chg-list").innerHTML = list(items.length);
        ev.currentTarget.remove();
      });
    });
  };
})();
