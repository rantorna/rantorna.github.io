"use strict";
// Visar uppdateringstiden överst på sidan: kopierar sidfotens "Data uppdaterad …" när sidans skript har fyllt i den.
// Mobil: rulla flikraden så att den aktuella fliken syns.
document.querySelector('.tabs a[aria-current="page"]')?.scrollIntoView({ block: "nearest", inline: "center" });

(() => {
  const foot = document.getElementById("updated"), top = document.getElementById("updated-top");
  if (!foot || !top) return;
  const copy = () => {
    const t = foot.textContent.replace(/^Data uppdaterad\s*/, "").replace(/\.$/, "");
    if (t) { top.textContent = `Uppdaterad ${t}`; top.hidden = false; }
  };
  new MutationObserver(copy).observe(foot, { childList: true, characterData: true, subtree: true });
  copy();
})();
