/* House design system: components.js (no build step, no dependencies).
   Load in <head> without defer so the entrance can hide items before first paint:
     <script src="/ds/components.js"></script>
   Gives window.DS:
     DS.play()            run the page's one entrance (auto on load unless <html data-ds-manual>)
     DS.icon(name, cls)   SVG markup for an icon from icons/sprite.svg
     DS.illo(name, opts)  Promise of an inline illustration element (recolored by tokens, optional line boil)
     DS.transition(fn)    run a DOM change as a view transition where supported
     DS.leave(el, kind)   animate an element out, resolves when done
     DS.haptic(button)    lay the iOS switch-tick label over a committing button
     DS.expand(head, on)  open or close a .ds-figrow / .ds-notice in place (taps are wired already; one open per group)
     DS.seg(el)           wire a segmented control (.ds-seg[role="radiogroup"] is wired on load); el.dsSeg.select(i)
     DS.meter(el, v)      set a .ds-meter's value (0 to 1) and its accessible value (meters are wired on load and on insert)
     DS.swap(el, opts)    show a sub-view pane at once, no waiting entrance; { fade: true } adds a 200 ms fade
     DS.select(el)        give a .ds-select the face that shows long choices whole (wired on load and on insert)
     DS.phases(el)        draw a .ds-phases bar, ticks and reader words from its legend (wired on load and on insert)
     DS.reduced           true when the person asked for reduced motion */
(function () {
  "use strict";
  var doc = document, html = doc.documentElement;
  var script = doc.currentScript;
  var BASE = script ? script.src.replace(/[^/]*$/, "") : "/ds/";
  var reduced = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  var played = false;

  if (!reduced) html.classList.add("ds-pre");

  function fontsReady(max) {
    var f = doc.fonts && doc.fonts.ready ? doc.fonts.ready : Promise.resolve();
    return Promise.race([f, new Promise(function (r) { setTimeout(r, max); })]);
  }
  function domReady() {
    return new Promise(function (r) { if (doc.readyState !== "loading") r(); else doc.addEventListener("DOMContentLoaded", r, { once: true }); });
  }

  // One entrance per screen. Items get --i in document order; the CSS caps the stagger at 6.
  // Only items that are on screen count (gaps2, 2026-11-20): items on a hidden screen or tab (display: none here or
  // above) used to take stagger slots, so the visible ones started late or all hit the cap. Hidden items wait
  // (data-enter-wait) and play their own entrance, counted from their own first item, the first time they are shown.
  // Items inside a closed .ds-collapse are not on screen either; they take no slot and open with the collapse.
  function shown(el) { return el.getClientRects().length > 0 && !el.closest(".ds-collapse:not(.is-open)"); }
  var waiting = null;
  function waitFor(el) {
    el.setAttribute("data-enter-wait", "");
    if (!waiting) waiting = new ResizeObserver(function (entries) {
      var now = [];
      entries.forEach(function (en) { var t = en.target; if (t.hasAttribute("data-enter-wait") && shown(t)) now.push(t); });
      if (!now.length) return;
      now.sort(function (a, b) { return a.compareDocumentPosition(b) & 4 ? -1 : 1; });
      now.forEach(function (t, i) {
        waiting.unobserve(t); t.removeAttribute("data-enter-wait");
        if (reduced) return;
        if (!t.dataset.dsOwnI) t.style.setProperty("--i", String(i));
        t.classList.add("ds-entering");
        setTimeout(function () { t.classList.remove("ds-entering"); }, 1500);
      });
    });
    waiting.observe(el);
  }
  function play() {
    if (played) return Promise.resolve();
    played = true;
    return domReady().then(function () { return fontsReady(900); }).then(function () {
      var items = doc.querySelectorAll("[data-enter]"), n = 0;
      for (var k = 0; k < items.length; k++) {
        var it = items[k], own = !!it.style.getPropertyValue("--i");
        if (own) it.dataset.dsOwnI = "1";
        if (it.closest(".ds-collapse:not(.is-open)")) continue;
        // A pane inside a sub-view switch (data-ds-swap, gaps3) never waits: when it is shown it is simply there.
        if (!shown(it) && it.closest("[data-ds-swap]")) { it.classList.add("ds-swap-skip"); continue; }
        if (!shown(it)) { if (!reduced && window.ResizeObserver) waitFor(it); continue; }
        if (!own) it.style.setProperty("--i", String(n++));
      }
      html.classList.remove("ds-pre");
      if (reduced) return;
      html.classList.add("ds-enter");
      // After the entrance, stop animating so later re-renders do not replay it.
      setTimeout(function () { html.classList.remove("ds-enter"); html.classList.add("ds-settled"); }, 1500);
    });
  }
  domReady().then(function () { if (!html.hasAttribute("data-ds-manual")) play(); });
  setTimeout(function () { html.classList.remove("ds-pre"); }, 2600); // never leave anything hidden

  // Sub-view swaps (gaps3, DESIGN.md 12.11). DS.swap(pane, { fade }) is for apps that show a pane their own way: it
  // drops any waiting entrance inside it and, with fade, plays one 200 ms opacity fade. Containers marked
  // data-ds-swap="fade" do the fade for their direct children on their own, each time one goes from hidden to shown.
  function swap(el, opts) {
    if (!el) return;
    var list = [el].concat(Array.prototype.slice.call(el.querySelectorAll("[data-enter]")));
    list.forEach(function (x) {
      if (!x.hasAttribute || !x.hasAttribute("data-enter")) return;
      if (x.hasAttribute("data-enter-wait")) { x.removeAttribute("data-enter-wait"); if (waiting) waiting.unobserve(x); }
      x.classList.remove("ds-entering"); x.classList.add("ds-swap-skip");
    });
    if (opts && opts.fade && !reduced) {
      el.classList.remove("ds-swap-in"); void el.offsetWidth; el.classList.add("ds-swap-in");
      setTimeout(function () { el.classList.remove("ds-swap-in"); }, 260);
    }
  }
  // The fade starts in the same task as the app's own toggle (a MutationObserver runs before the next paint), so the
  // new pane never shows at full strength first. It watches hidden, class and style on the box's direct children.
  domReady().then(function () {
    if (!window.MutationObserver) return;
    doc.querySelectorAll('[data-ds-swap="fade"]').forEach(function (box) {
      var seen = new WeakMap();
      Array.prototype.forEach.call(box.children, function (c) { seen.set(c, c.getClientRects().length > 0); });
      new MutationObserver(function (recs) {
        if (box.getAttribute("data-ds-swap") !== "fade") return;
        if (!recs.some(function (r) { return r.target === box || r.target.parentElement === box; })) return; // only the panes themselves
        Array.prototype.forEach.call(box.children, function (pane) {
          var now = pane.getClientRects().length > 0, was = seen.get(pane);
          seen.set(pane, now);
          if (was === false && now && played) swap(pane, { fade: true });
        });
      }).observe(box, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "class", "style"] });
    });
  });

  // iOS only applies :active when a touch listener exists.
  doc.addEventListener("touchstart", function () {}, { passive: true });

  function icon(name, cls) {
    return '<svg class="ds-icon' + (cls ? " " + cls : "") + '" aria-hidden="true" focusable="false"><use href="' + BASE + "icons/sprite.svg#i-" + name + '"></use></svg>';
  }

  var illoCache = {};
  function illo(name, opts) {
    opts = opts || {};
    // window.DS_ILLO_SRC (optional) maps a name to another URL, e.g. the Design System artifact's uploads.
    var src = (window.DS_ILLO_SRC && window.DS_ILLO_SRC[name]) || BASE + "illustrations/" + name + ".svg";
    var p = illoCache[name] || (illoCache[name] = fetch(src).then(function (r) {
      if (!r.ok) throw new Error(r.status); return r.text();
    }));
    return p.then(function (txt) {
      var svg = new DOMParser().parseFromString(txt, "image/svg+xml").documentElement;
      svg = doc.importNode(svg, true);
      svg.removeAttribute("width"); svg.removeAttribute("height");
      svg.setAttribute("class", "ds-illo" + (opts.green ? " ds-illo--green" : "") + (opts.boil && !reduced ? " ds-boil" : "") + (opts.cls ? " " + opts.cls : ""));
      svg.setAttribute("aria-hidden", "true");
      if (opts.boil && !reduced) startBoil();
      return svg;
    });
  }

  // Line boil: three turbulence seeds swapped every 120 ms, like redrawn animation frames.
  var boiling = false;
  function startBoil() {
    if (boiling) return; boiling = true;
    var ns = "http://www.w3.org/2000/svg", defs = doc.createElementNS(ns, "svg");
    defs.setAttribute("width", "0"); defs.setAttribute("height", "0"); defs.setAttribute("aria-hidden", "true");
    defs.style.position = "absolute";
    var inner = "";
    for (var i = 0; i < 3; i++) inner += '<filter id="ds-boil-' + i + '"><feTurbulence type="fractalNoise" baseFrequency="0.022" numOctaves="2" seed="' + (i * 7 + 3) + '"/><feDisplacementMap in="SourceGraphic" scale="3.2"/></filter>';
    defs.innerHTML = inner;
    doc.body.appendChild(defs);
    var f = 0;
    setInterval(function () {
      if (doc.hidden) return;
      f = (f + 1) % 3;
      var els = doc.querySelectorAll(".ds-boil");
      for (var k = 0; k < els.length; k++) els[k].style.filter = "url(#ds-boil-" + f + ")";
    }, 120);
  }

  function transition(fn) {
    if (reduced || !doc.startViewTransition) { fn(); return Promise.resolve(); }
    try { return doc.startViewTransition(fn).finished.catch(function () {}); } catch (e) { fn(); return Promise.resolve(); }
  }

  function leave(el, kind) {
    if (reduced || !el.animate) return Promise.resolve();
    var frames = kind === "down"
      ? [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(16px) scale(.94)" }]
      : [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateX(36px) rotate(2deg) scale(.95)" }];
    var a = el.animate(frames, { duration: 260, easing: "cubic-bezier(0.5, 0, 0.75, 0)", fill: "forwards" });
    return a.finished.catch(function () {});
  }

  // iOS 26.5+: the switch tick only plays when the person's own tap lands on a label for a switch input.
  // A transparent label over the button takes the tap, ticks, then clicks the button. Keyboard focus stays on the button.
  var hapticN = 0;
  function haptic(btn) {
    if (!btn || btn.dataset.dsHaptic) return;
    var ios = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    if (!ios) return;
    btn.dataset.dsHaptic = "1";
    var id = "ds-haptic-" + (++hapticN);
    var wrap = doc.createElement("span"); wrap.className = "ds-haptic-wrap";
    btn.parentNode.insertBefore(wrap, btn); wrap.appendChild(btn);
    var label = doc.createElement("label"); label.className = "ds-haptic"; label.setAttribute("for", id); label.setAttribute("aria-hidden", "true");
    var input = doc.createElement("input"); input.type = "checkbox"; input.id = id; input.setAttribute("switch", ""); input.tabIndex = -1;
    label.appendChild(input); wrap.appendChild(label);
    label.addEventListener("pointerdown", function () { btn.classList.add("is-pressed"); });
    ["pointerup", "pointercancel", "pointerleave"].forEach(function (t) { label.addEventListener(t, function () { btn.classList.remove("is-pressed"); }); });
    label.addEventListener("click", function (e) { if (e.target === input) return; setTimeout(function () { if (!btn.disabled) btn.click(); }, 0); });
  }


  // Figure rows and notices open in place (DESIGN.md 12). One open per group (.ds-list, .ds-notices or [data-ds-group]).
  var HEADS = ".ds-figrow__head, .ds-notice__head, .ds-symrow__head";
  function expand(head, on) {
    var row = head.parentElement, col = null;
    var id = head.getAttribute("aria-controls");
    col = id ? doc.getElementById(id) : row.querySelector(":scope > .ds-collapse");
    if (!col) return;
    if (on === undefined) on = head.getAttribute("aria-expanded") !== "true";
    if (on) {
      var group = row.closest("[data-ds-group], .ds-list, .ds-notices");
      if (group) group.querySelectorAll(HEADS).forEach(function (o) { if (o !== head && o.getAttribute("aria-expanded") === "true") expand(o, false); });
    }
    head.setAttribute("aria-expanded", String(on));
    col.classList.toggle("is-open", on);
  }
  doc.addEventListener("click", function (e) {
    var head = e.target.closest && e.target.closest(HEADS);
    if (!head || head.tagName !== "BUTTON" || head.disabled || head.hasAttribute("data-ds-manual")) return;
    expand(head);
  });

  // Segmented control: radiogroup semantics, roving tabindex, arrow keys, a pill that slides on the spatial spring.
  function seg(el) {
    if (!el || el.dsSeg) return el && el.dsSeg;
    var opts = Array.prototype.slice.call(el.querySelectorAll(":scope > .ds-seg__opt"));
    if (!opts.length) return;
    var pill = el.querySelector(":scope > .ds-seg__pill");
    if (!pill) { pill = doc.createElement("span"); pill.className = "ds-seg__pill"; pill.setAttribute("aria-hidden", "true"); el.insertBefore(pill, el.firstChild); }
    el.style.setProperty("--seg-n", String(opts.length));
    var cur = Math.max(0, opts.findIndex(function (o) { return o.getAttribute("aria-checked") === "true"; }));
    function paint(i, still) {
      if (still) el.classList.add("is-still");
      el.style.setProperty("--seg-i", String(i));
      opts.forEach(function (o, k) { o.setAttribute("role", "radio"); o.setAttribute("aria-checked", String(k === i)); o.tabIndex = k === i ? 0 : -1; });
      if (still) { void pill.offsetWidth; el.classList.remove("is-still"); }
    }
    function select(i, focus) {
      if (i < 0 || i >= opts.length || opts[i].disabled) return;
      if (focus) opts[i].focus();
      if (i === cur) return;
      cur = i; paint(i);
      el.dispatchEvent(new CustomEvent("seg-change", { bubbles: true, detail: { index: i, value: opts[i].dataset.value || opts[i].textContent.trim() } }));
    }
    opts.forEach(function (o, k) { o.addEventListener("click", function () { select(k); }); });
    el.addEventListener("keydown", function (e) {
      var k = opts.indexOf(doc.activeElement); if (k < 0) return;
      var n = opts.length, to = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") to = (k + 1) % n;
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") to = (k - 1 + n) % n;
      else if (e.key === "Home") to = 0; else if (e.key === "End") to = n - 1;
      if (to === null) return;
      e.preventDefault();
      while (opts[to].disabled && to !== k) to = (to + (e.key === "ArrowLeft" || e.key === "ArrowUp" ? n - 1 : 1)) % n;
      select(to, true);
    });
    paint(cur, true);
    el.classList.add("is-live");
    el.dsSeg = { select: function (i) { select(i); }, get index() { return cur; } };
    return el.dsSeg;
  }
  domReady().then(function () { doc.querySelectorAll('.ds-seg[role="radiogroup"]').forEach(seg); });

  // Meter (DESIGN.md 12.4): data-value (0 to 1) sets --v and the accessible value. A meter inside a button is hidden
  // from readers and its words go in a .ds-sr span beside it, because a button flattens the roles inside it.
  // Call DS.meter(el, value) to change one; new meters anywhere in the page are wired as they arrive.
  function meter(el, value) {
    if (!el) return;
    if (value !== undefined) el.setAttribute("data-value", String(value));
    var v = parseFloat(el.getAttribute("data-value"));
    if (isNaN(v)) v = parseFloat(getComputedStyle(el).getPropertyValue("--v")) || 0;
    v = Math.max(0, Math.min(1, v));
    el.style.setProperty("--v", String(v));
    var words = el.getAttribute("data-label") || Math.round(v * 100) + "%";
    var inButton = el.parentElement && el.parentElement.closest("button, [role='button']");
    if (inButton) {
      el.setAttribute("aria-hidden", "true"); el.removeAttribute("role");
      var sr = el.nextElementSibling && el.nextElementSibling.classList.contains("ds-sr") ? el.nextElementSibling : null;
      if (!sr) { sr = doc.createElement("span"); sr.className = "ds-sr"; el.insertAdjacentElement("afterend", sr); }
      sr.textContent = ", " + words;
    } else {
      el.setAttribute("role", "meter"); el.setAttribute("aria-valuemin", "0"); el.setAttribute("aria-valuemax", "100");
      el.setAttribute("aria-valuenow", String(Math.round(v * 100))); el.setAttribute("aria-valuetext", words);
    }
  }
  // Select with long choices (gaps3, DESIGN.md 12.9): a face that shows the whole chosen text, wrapping, under the
  // real select (transparent, on top), so a tap still opens the native picker. The face follows change and input, and
  // value or selectedIndex set from code (those setters are wrapped on this one element).
  function select(el) {
    if (!el) return;
    var sel = el.querySelector("select"); if (!sel) return;
    var face = el.querySelector(":scope > .ds-select__show");
    if (!face) {
      face = doc.createElement("span"); face.className = "ds-select__show"; face.setAttribute("aria-hidden", "true");
      sel.insertAdjacentElement("afterend", face);
      var paint = function () { var o = sel.options[sel.selectedIndex]; face.textContent = o ? o.text : ""; };
      sel.addEventListener("change", paint); sel.addEventListener("input", paint);
      ["value", "selectedIndex"].forEach(function (k) {
        var d = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, k);
        if (d && d.set) try { Object.defineProperty(sel, k, { configurable: true, get: function () { return d.get.call(sel); }, set: function (v) { d.set.call(sel, v); paint(); } }); } catch (e) {}
      });
      el.dsPaint = paint;
      el.classList.add("is-live");
    }
    el.dsPaint();
  }

  // Phase bar (gaps3, DESIGN.md 12.12): the author writes the legend; this draws the bar, the dots, the dates on ticks
  // and the reader words, and lays the dates out again when the width changes. Dates that would touch drop a row.
  var phaseRO = window.ResizeObserver ? new ResizeObserver(function (en) { en.forEach(function (e) { layPhases(e.target.closest(".ds-phases")); }); }) : null;
  function phases(el) {
    if (!el) return;
    var legend = el.querySelector(".ds-phases__legend"); if (!legend) return;
    var items = Array.prototype.slice.call(legend.children);
    if (!el.dsPhases) {
      var bar = doc.createElement("div"); bar.className = "ds-phases__bar"; bar.setAttribute("aria-hidden", "true");
      var ticks = doc.createElement("div"); ticks.className = "ds-phases__ticks"; ticks.setAttribute("aria-hidden", "true");
      legend.insertAdjacentElement("beforebegin", bar); legend.insertAdjacentElement("beforebegin", ticks);
      el.dsPhases = { bar: bar, ticks: ticks };
      el.classList.add("is-live");
      if (phaseRO) phaseRO.observe(ticks);
    }
    var P = el.dsPhases, total = 0;
    P.bar.innerHTML = ""; P.ticks.innerHTML = "";
    items.forEach(function (li, i) {
      var w = parseFloat(li.getAttribute("data-weight")); if (!(w > 0)) w = 1;
      var tone = li.classList.contains("is-over") ? "over" : String(Math.min(i + 1, 5));
      li.setAttribute("data-ph", tone);
      var part = doc.createElement("span"); part.className = "ds-phases__part"; part.setAttribute("data-ph", tone); part.style.flexGrow = String(w);
      P.bar.appendChild(part);
      if (!li.querySelector(":scope > .ds-phases__dot")) { var dot = doc.createElement("span"); dot.className = "ds-phases__dot"; dot.setAttribute("aria-hidden", "true"); li.insertBefore(dot, li.firstChild); }
      var from = li.getAttribute("data-from"), to = items[i + 1] ? items[i + 1].getAttribute("data-from") : el.getAttribute("data-end");
      var sr = li.querySelector(":scope > .ds-phases__when"); if (!sr) { sr = doc.createElement("span"); sr.className = "ds-phases__when"; li.appendChild(sr); }
      sr.textContent = from ? (to ? ", " + from + " to " + to : ", from " + from) : "";
      li.dsStart = total; total += w;
    });
    P.total = total;
    P.marks = [];
    items.forEach(function (li) { var f = li.getAttribute("data-from"); if (f) P.marks.push({ at: li.dsStart / total, text: f, li: li }); });
    if (el.getAttribute("data-end")) P.marks.push({ at: 1, text: el.getAttribute("data-end"), end: true });
    P.marks.forEach(function (m) { var t = doc.createElement("span"); t.className = "ds-phases__tick"; t.textContent = m.text; P.ticks.appendChild(t); m.el = t; });
    layPhases(el);
  }
  // Lay the dates out: each date sits left of its tick, or right of it, on row 0 or row 1. A small search over those
  // choices (at most 4^6 for six dates) keeps every date clear of the others and of any tick that runs past it, and
  // prefers one row and left-aligned dates. A date that cannot fit anywhere leaves the tick row and shows in its key
  // entry instead ("Move, Feb 13 to Feb 24"), so nothing overlaps at any width.
  function layPhases(el) {
    var P = el && el.dsPhases; if (!P || !P.marks) return;
    var cw = P.ticks.clientWidth; if (!cw) return;
    var M = P.marks.map(function (m) { m.el.style.left = "0px"; m.el.classList.remove("is-right", "is-dropped"); return { x: m.at * cw, w: m.el.offsetWidth, m: m }; });
    var GAP = 12, PAD = 4, best = null, cur = [];
    function fits(i, o) {
      if (o.drop) return true;
      if (o.right && !M[i].m.end) return false; // a start date never flips under the phase before it (critic round 2); it goes to the key
      var a = M[i], l = o.right ? a.x - a.w : a.x, r = l + a.w;
      if (l < -0.5 || r > cw + 0.5) return false;
      for (var j = 0; j < i; j++) {
        var q = cur[j]; if (q.drop) continue;
        if (q.row === o.row && l < q.r + GAP && q.l < r + GAP) return false;
        if (q.row < o.row && a.x >= q.l - PAD && a.x <= q.r + PAD) return false;
        if (q.row > o.row && M[j].x >= l - PAD && M[j].x <= r + PAD) return false;
      }
      o.l = l; o.r = r; return true;
    }
    // A date left of its tick sits under the phase before it and reads as that phase's break, so flipping costs more
    // than dropping a row (critic, gaps3); the end date is right-aligned by nature and costs nothing.
    function cost(list) { var c = 0, two = false; list.forEach(function (o, i) { if (o.drop) c += 1000; else { if (o.row) { c += 10; two = true; } if (o.right && !M[i].m.end) c += 20; } }); return c + (two ? 5 : 0); }
    var OPTS = [{ row: 0, right: false }, { row: 0, right: true }, { row: 1, right: false }, { row: 1, right: true }, { drop: true }];
    (function dfs(i) {
      if (best && cost(cur) >= best.c) return;
      if (i === M.length) { best = { c: cost(cur), list: cur.map(function (o) { return Object.assign({}, o); }) }; return; }
      OPTS.forEach(function (base) { var o = Object.assign({}, base); if (fits(i, o)) { cur.push(o); dfs(i + 1); cur.pop(); } });
    })(0);
    var rows = 1, items = el.querySelectorAll(".ds-phases__legend > li"), lastLi = items[items.length - 1];
    best.list.forEach(function (o, i) {
      var t = M[i].m.el, li = M[i].m.li || (M[i].m.end && o.drop ? lastLi : null); // a dropped end date shows with the last phase
      t.classList.toggle("is-dropped", !!o.drop);
      if (li && (o.drop || !M[i].m.end)) li.classList.toggle("is-dated", !!o.drop || li.classList.contains("is-dated") && !M[i].m.li);
      if (o.drop) return;
      if (o.row) rows = 2;
      t.classList.toggle("is-right", o.right);
      t.style.left = o.l + "px"; t.setAttribute("data-row", String(o.row)); t.style.setProperty("--row", String(o.row));
    });
    P.ticks.style.setProperty("--ph-rows", String(rows));
  }

  domReady().then(function () {
    doc.querySelectorAll(".ds-meter").forEach(function (m) { meter(m); });
    doc.querySelectorAll(".ds-select").forEach(select);
    doc.querySelectorAll(".ds-phases").forEach(phases);
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(function () { doc.querySelectorAll(".ds-phases").forEach(layPhases); });
    if (!window.MutationObserver) return;
    new MutationObserver(function (list) {
      list.forEach(function (r) {
        if (r.type === "attributes") { if (r.target.classList.contains("ds-meter")) meter(r.target); return; }
        r.addedNodes.forEach(function (nd) {
          if (nd.nodeType !== 1) return;
          if (nd.classList.contains("ds-meter")) meter(nd);
          if (nd.classList.contains("ds-select")) select(nd);
          if (nd.classList.contains("ds-phases")) phases(nd);
          if (!nd.querySelectorAll) return;
          nd.querySelectorAll(".ds-meter").forEach(function (m) { meter(m); });
          nd.querySelectorAll(".ds-select").forEach(select);
          nd.querySelectorAll(".ds-phases").forEach(phases);
        });
      });
    }).observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-value", "data-label"] });
  });

  // Adopting the system (gaps3, DESIGN.md "Adopting the system"): an app's old stylesheet that sets house tokens on
  // :root or html, loaded after tokens.css, silently beats them (Finance's styles.css pinned --ink and --series-1, so
  // dark mode never reached them). Say so once in the console, naming the file and the tokens.
  window.addEventListener("load", function () {
    var sheets = Array.prototype.slice.call(doc.styleSheets), names = {}, tok = null;
    function rules(sh) { try { return sh.cssRules || []; } catch (e) { return []; } }
    function walk(list, fn) { Array.prototype.forEach.call(list, function (r) { if (r.cssRules && !r.selectorText) walk(r.cssRules, fn); else if (r.selectorText) fn(r); }); }
    function rootish(sel) { return sel.split(",").some(function (x) { return /^\s*(:root|html)(\[[^\]]*\]|:not\([^)]*\))*\s*$/.test(x); }); }
    sheets.forEach(function (sh) { if (sh.href && /\/tokens\.css(\?|$)/.test(sh.href)) tok = sh; });
    if (!tok) return;
    walk(rules(tok), function (r) { if (!rootish(r.selectorText)) return; for (var i = 0; i < r.style.length; i++) if (r.style[i].indexOf("--") === 0) names[r.style[i]] = 1; });
    sheets.forEach(function (sh) {
      if (sh === tok || (sh.href && /\/ds\//.test(sh.href) && /\/(motion|components|gallery)\.css/.test(sh.href))) return;
      var hit = {};
      walk(rules(sh), function (r) { if (!rootish(r.selectorText)) return; for (var i = 0; i < r.style.length; i++) if (names[r.style[i]]) hit[r.style[i]] = 1; });
      var k = Object.keys(hit);
      if (k.length) console.warn("DS: " + (sh.href || "an inline <style>").replace(/^.*\//, "") + " sets house tokens on :root (" + k.slice(0, 8).join(", ") + (k.length > 8 ? ", ..." : "") + "), which overrides tokens.css and its dark mode. Remove them from that file (DESIGN.md, Adopting the system).");
    });
  });

  window.DS = { play: play, icon: icon, illo: illo, transition: transition, leave: leave, haptic: haptic, expand: expand, seg: seg, meter: meter, swap: swap, select: select, phases: phases, reduced: reduced, base: BASE };
})();
