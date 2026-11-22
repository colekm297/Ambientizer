/* Ambientizer in the house design system (2026-11-22): the small bits of behaviour that are purely visual.
   - the header illustration (one Open Doodle, recoloured, line boil)
   - the green pen under the active tab (follows the tab app.js activates)
   - the ink tide: a hand-drawn line of sound on the Generate card. It writes itself in once, swells while the
     pointer or focus is on Generate, surges on press, and flows while a take is being made.
   Nothing here changes data, requests or app.js behaviour. */
(function () {
  "use strict";
  var reduced = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  var NS = "http://www.w3.org/2000/svg";

  // ---- header illustration
  var illoHost = document.getElementById("house-illo");
  if (illoHost && window.DS && DS.illo) {
    DS.illo("meditating", { boil: true }).then(function (svg) { illoHost.appendChild(svg); }).catch(function () {});
  }

  // ---- tab pen
  // Redraws only when the active tab changes (Marks.pen adds a class to the tab, so a class observer alone would loop).
  var pennedTab = null, penReady = false;
  function penActiveTab() {
    if (!window.Marks || !penReady) return;
    var a = document.querySelector(".tab-nav .tab-btn.active");
    if (!a || a === pennedTab) return;
    document.querySelectorAll(".tab-nav .tab-btn > .ds-mark").forEach(function (m) { m.remove(); });
    pennedTab = a;
    Marks.pen(a);
  }
  var nav = document.querySelector(".tab-nav");
  if (nav) {
    nav.addEventListener("click", function (e) { if (e.target.closest(".tab-btn")) setTimeout(penActiveTab, 0); });
    new MutationObserver(function () { setTimeout(penActiveTab, 0); })
      .observe(nav, { subtree: true, attributes: true, attributeFilter: ["class"] });
  }

  // ---- the ink tide
  var tide = document.getElementById("ink-tide");
  function rng(seed) { var h = seed >>> 0; return function () { h ^= h << 13; h ^= h >>> 17; h ^= h << 5; return ((h >>> 0) % 10000) / 10000; }; }
  function wavePath(seed, phase, amp) {
    // A slow sine with a second, slower swell under it, tapering at both ends, with a little hand wobble.
    var r = rng(seed), W = 280, mid = 45, n = 72, d = "";
    for (var i = 0; i <= n; i++) {
      var t = i / n, x = t * W;
      var env = Math.pow(Math.sin(Math.PI * t), 1.4);
      var y = mid + env * amp * (Math.sin(t * Math.PI * 5 + phase) * 0.72 + Math.sin(t * Math.PI * 1.6 + phase * 0.5) * 0.28) + (r() - 0.5) * 1.6;
      d += (i ? " L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }
    return d;
  }
  if (tide) {
    var g = document.createElementNS(NS, "g"); g.setAttribute("class", "tide-wave");
    [["tide-echo", 7, 1.9, 20], ["tide-main", 11, 0.4, 26]].forEach(function (s) {
      var p = document.createElementNS(NS, "path");
      p.setAttribute("class", s[0]); p.setAttribute("d", wavePath(s[1], s[2], s[3])); p.setAttribute("vector-effect", "non-scaling-stroke");
      g.appendChild(p);
    });
    tide.appendChild(g);
    g.querySelectorAll("path").forEach(function (p) { try { p.style.setProperty("--len", Math.ceil(p.getTotalLength() * 1.2)); } catch (e) {} });
    if (!reduced) {
      tide.classList.add("is-writing");
      setTimeout(function () { tide.classList.remove("is-writing"); }, 3200);
    }

    var btn = document.getElementById("generate-btn");
    if (btn) {
      var near = function (on) { tide.classList.toggle("is-near", on && !btn.disabled); };
      btn.addEventListener("pointerenter", function () { near(true); });
      btn.addEventListener("pointerleave", function () { near(false); });
      btn.addEventListener("focus", function () { near(true); });
      btn.addEventListener("blur", function () { near(false); });
      btn.addEventListener("pointerdown", function () {
        if (btn.disabled) return;
        tide.classList.add("is-surging");
        setTimeout(function () { tide.classList.remove("is-surging"); }, 420);
      });
    }
    // While a take is being made (the progress panel is showing), the line flows.
    var prog = document.getElementById("progress-panel");
    if (prog) {
      var sync = function () { tide.classList.toggle("is-working", !prog.classList.contains("hidden")); };
      new MutationObserver(sync).observe(prog, { attributes: true, attributeFilter: ["class"] });
      sync();
    }
  }

  // ---- phone player: one compact row, the rest behind one tap (the button only shows on the phone, via CSS)
  var gp = document.getElementById("global-player");
  if (gp && !gp.querySelector(".gp-more")) {
    var more = document.createElement("button");
    more.type = "button"; more.className = "gp-more";
    more.setAttribute("aria-expanded", "false"); more.setAttribute("aria-label", "More player controls");
    more.title = "Rating, previous, next, times and loop";
    more.addEventListener("click", function () {
      var open = !gp.classList.contains("gp-open");
      gp.classList.toggle("gp-open", open);
      more.setAttribute("aria-expanded", open ? "true" : "false");
    });
    gp.appendChild(more);
  }

  // ---- measured layout: the page clears the player, and on wide screens Settings ends above it
  function measure() {
    var root = document.documentElement, bar = document.getElementById("global-player");
    var h = bar && !bar.classList.contains("hidden") ? bar.offsetHeight : 0;
    root.style.setProperty("--gp-h", h + "px");
    var set = document.querySelector(".create-col-settings");
    if (set && set.offsetParent) {
      root.style.setProperty("--settings-top", (set.getBoundingClientRect().top + window.scrollY) + "px");
      // Settings ends above the player wherever the page is scrolled: its height comes from where it sits now.
      var room = window.innerHeight - set.getBoundingClientRect().top - h - 16;
      root.style.setProperty("--settings-max", Math.max(320, Math.round(room)) + "px");
    }
  }
  var measureQueued = false;
  // The page scrolls inside .container now (the shell), so listen in the capture phase to hear any scroller.
  document.addEventListener("scroll", function () {
    if (measureQueued) return; measureQueued = true;
    requestAnimationFrame(function () { measureQueued = false; measure(); });
  }, { passive: true, capture: true });
  window.addEventListener("resize", measure);
  setTimeout(measure, 2600);
  if (gp) new MutationObserver(measure).observe(gp, { attributes: true, attributeFilter: ["class"] });
  setTimeout(measure, 0); setTimeout(measure, 1200);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);

  // ---- Listen: the ink faders. The track inks in green up to the bead.
  function fill(r) {
    var min = +r.min || 0, max = r.max === "" ? 100 : +r.max, v = +r.value;
    r.style.setProperty("--fill", (max > min ? ((v - min) / (max - min)) * 100 : 0) + "%");
  }
  function fillAll() { document.querySelectorAll("#tab-listen input[type=range], #tab-create input[type=range]").forEach(fill); }
  document.addEventListener("input", function (e) { if (e.target.matches && e.target.matches("input[type=range]")) fill(e.target); }, true);
  document.addEventListener("change", function (e) { if (e.target.matches && e.target.matches("input[type=range]")) fill(e.target); }, true);
  if (nav) nav.addEventListener("click", function () { setTimeout(fillAll, 60); setTimeout(fillAll, 600); });
  var listen = document.getElementById("tab-listen");
  if (listen) new MutationObserver(function () { clearTimeout(fillAll._t); fillAll._t = setTimeout(fillAll, 50); }).observe(listen, { childList: true, subtree: true });
  setTimeout(fillAll, 500); setTimeout(fillAll, 2500);

  // ---- Visuals: the developing print. A new scene image clears in like a print in the tray.
  document.addEventListener("load", function (e) {
    var img = e.target;
    if (!img || img.tagName !== "IMG" || reduced || !img.closest || !img.closest("#tab-visuals") || !img.getAttribute("src")) return;
    img.classList.remove("house-develop"); void img.offsetWidth; img.classList.add("house-develop");
    setTimeout(function () { img.classList.remove("house-develop"); }, 1700);
  }, true);

  // ---- Publish: the green check. The first time the tab shows a live YouTube connection, a green pen line
  // draws under it, once.
  var ytText = document.getElementById("yt-status-text"), ytChecked = false;
  function ytCheck() {
    if (ytChecked || !ytText || !window.Marks) return;
    var tab = document.getElementById("tab-publish");
    if (!tab || !tab.classList.contains("active") || !/^Connected/i.test(ytText.textContent.trim())) return;
    ytChecked = true;
    setTimeout(function () { Marks.underline(ytText, { color: "var(--mark-green)" }); }, reduced ? 0 : 250);
  }
  if (ytText) new MutationObserver(ytCheck).observe(ytText, { childList: true, characterData: true, subtree: true });
  if (nav) nav.addEventListener("click", function () { setTimeout(ytCheck, 120); });

  // ---- Distribute: the catalog shows 24 rows at a time; "Show more" reveals the next 24. Nothing is removed.
  var cat = document.getElementById("dist-catalog-list"), PAGE = 24;
  function capCatalog() {
    if (!cat) return;
    var rows = cat.querySelectorAll(":scope > .distribute-row"), shown = +(cat.dataset.shown || PAGE);
    rows.forEach(function (r, i) { r.classList.toggle("house-cap-hidden", i >= shown); });
    var more = cat.querySelector(":scope > .house-more");
    var left = rows.length - Math.min(shown, rows.length);
    if (left > 0) {
      if (!more) {
        more = document.createElement("button"); more.type = "button"; more.className = "btn btn-secondary house-more";
        more.addEventListener("click", function () { cat.dataset.shown = String((+(cat.dataset.shown || PAGE)) + PAGE); capCatalog(); });
      }
      more.textContent = "Show more (" + left + ")";
      cat.appendChild(more);
    } else if (more) more.remove();
  }
  if (cat) {
    var capBusy = false;
    new MutationObserver(function () {
      if (capBusy) return; capBusy = true;
      if (!cat.querySelector(":scope > .house-more") && !cat.dataset.capped) cat.dataset.shown = String(PAGE);
      capCatalog(); cat.dataset.capped = "1";
      setTimeout(function () { capBusy = false; delete cat.dataset.capped; }, 0);
    }).observe(cat, { childList: true });
  }

  // Marks draw after the entrance has settled, so the pen lands on a still page.
  function start() { setTimeout(function () { penReady = true; penActiveTab(); }, reduced ? 0 : 650); }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(start); else window.addEventListener("load", start);
})();
