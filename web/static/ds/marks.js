/* House design system: marks.js. Hand-drawn marks that point at things, drawn with a felt-pen stroke.
   Load after components.js:  <script src="/ds/marks.js" defer></script>

   THE RULES (also in DESIGN.md, Marks). A mark means "look here". If it does not mean that, it does not go on.
   - Marks.circle(el)     circle ONE number or word that needs him (a count waiting on him, a changed value).
                          At most one circle per screen. Never around a whole card or a sentence.
   - Marks.underline(el)  under a changed value or the one word that answers the screen's question.
                          The active tab gets its own pen line (Marks.pen), which does not count.
   - Marks.scribble(el)   a highlighter scribble behind a short label (two or three words) that is new.
                          Never behind reading text, never two on one screen.
   - Marks.arc(el, opts)  a curved arrow pointing at the one thing to tap next. Empty states and first runs only.
   - Marks.note(el, text) a hand-lettered note of two to four words beside a number or item ("up from 1", "new").
                          At most one per screen. A note is a graphic, never reading text, never a sentence.
   - Total: no more than three marks on a screen, plus the tab pen. A section head's pen stroke (.ds-section-head--pen)
     counts as one. marks.js warns in the console past that.
   - Colors: amber (--mark) by default, green (--mark-green) for the tab pen and "done". Nothing else.
   - Marks draw themselves once, on first view (about 0.6 s). They never loop and never redraw on refresh.

   Pen strokes: perfect-freehand 1.2.3 by Steve Ruiz, MIT licence (vendor/perfect-freehand.LICENSE), inlined below. */
(function () {
  "use strict";
  var PF = (function () {
const{PI:e}=Math,t=e+1e-4,n=.5,r=[1,1];function i(e,t,n,r=e=>e){return e*r(.5-t*(.5-n))}const{min:a}=Math;function o(e,t,n){let r=a(1,t/n);return a(1,e+(a(1,1-r)-e)*(r*.275))}function s(e){return[-e[0],-e[1]]}function c(e,t){return[e[0]+t[0],e[1]+t[1]]}function l(e,t,n){return e[0]=t[0]+n[0],e[1]=t[1]+n[1],e}function u(e,t){return[e[0]-t[0],e[1]-t[1]]}function d(e,t,n){return e[0]=t[0]-n[0],e[1]=t[1]-n[1],e}function f(e,t){return[e[0]*t,e[1]*t]}function p(e,t,n){return e[0]=t[0]*n,e[1]=t[1]*n,e}function m(e,t){return[e[0]/t,e[1]/t]}function h(e){return[e[1],-e[0]]}function g(e,t){let n=t[0];return e[0]=t[1],e[1]=-n,e}function ee(e,t){return e[0]*t[0]+e[1]*t[1]}function _(e,t){return e[0]===t[0]&&e[1]===t[1]}function v(e){return Math.hypot(e[0],e[1])}function y(e,t){let n=e[0]-t[0],r=e[1]-t[1];return n*n+r*r}function b(e){return m(e,v(e))}function x(e,t){return Math.hypot(e[1]-t[1],e[0]-t[0])}function S(e,t,n){let r=Math.sin(n),i=Math.cos(n),a=e[0]-t[0],o=e[1]-t[1],s=a*i-o*r,c=a*r+o*i;return[s+t[0],c+t[1]]}function C(e,t,n,r){let i=Math.sin(r),a=Math.cos(r),o=t[0]-n[0],s=t[1]-n[1],c=o*a-s*i,l=o*i+s*a;return e[0]=c+n[0],e[1]=l+n[1],e}function w(e,t,n){return c(e,f(u(t,e),n))}function te(e,t,n,r){let i=n[0]-t[0],a=n[1]-t[1];return e[0]=t[0]+i*r,e[1]=t[1]+a*r,e}function T(e,t,n){return c(e,f(t,n))}const E=[0,0],D=[0,0],O=[0,0];function k(e,n){let r=T(e,b(h(u(e,c(e,[1,1])))),-n),i=[],a=1/13;for(let n=a;n<=1;n+=a)i.push(S(r,e,t*2*n));return i}function A(e,n,r){let i=[],a=1/r;for(let r=a;r<=1;r+=a)i.push(S(n,e,t*r));return i}function j(e,t,n){let r=u(t,n),i=f(r,.5),a=f(r,.51);return[u(e,i),u(e,a),c(e,a),c(e,i)]}function M(e,n,r,i){let a=[],o=T(e,n,r),s=1/i;for(let n=s;n<1;n+=s)a.push(S(o,e,t*3*n));return a}function ne(e,t,n){return[c(e,f(t,n)),c(e,f(t,n*.99)),u(e,f(t,n*.99)),u(e,f(t,n))]}function N(e,t,n){return e===!1||e===void 0?0:e===!0?Math.max(t,n):e}function re(e,t,n){return e.slice(0,10).reduce((e,r)=>{let i=r.pressure;return t&&(i=o(e,r.distance,n)),(e+i)/2},e[0].pressure)}function P(e,n={}){let{size:r=16,smoothing:a=.5,thinning:f=.5,simulatePressure:m=!0,easing:_=e=>e,start:v={},end:b={},last:x=!1}=n,{cap:S=!0,easing:w=e=>e*(2-e)}=v,{cap:T=!0,easing:P=e=>--e*e*e+1}=b;if(e.length===0||r<=0)return[];let F=e[e.length-1].runningLength,I=N(v.taper,r,F),L=N(b.taper,r,F),R=(r*a)**2,z=[],B=[],V=re(e,m,r),H=i(r,f,e[e.length-1].pressure,_),U,W=e[0].vector,G=e[0].point,K=G,q=G,J=K,Y=!1;for(let n=0;n<e.length;n++){let{pressure:a}=e[n],{point:s,vector:h,distance:v,runningLength:b}=e[n],x=n===e.length-1;if(!x&&F-b<3)continue;f?(m&&(a=o(V,v,r)),H=i(r,f,a,_)):H=r/2,U===void 0&&(U=H);let S=b<I?w(b/I):1,T=F-b<L?P((F-b)/L):1;H=Math.max(.01,H*Math.min(S,T));let k=(x?e[n]:e[n+1]).vector,A=x?1:ee(h,k),j=ee(h,W)<0&&!Y,M=A!==null&&A<0;if(j||M){g(E,W),p(E,E,H);for(let e=0;e<=1;e+=.07692307692307693)d(D,s,E),C(D,D,s,t*e),q=[D[0],D[1]],z.push(q),l(O,s,E),C(O,O,s,t*-e),J=[O[0],O[1]],B.push(J);G=q,K=J,M&&(Y=!0);continue}if(Y=!1,x){g(E,h),p(E,E,H),z.push(u(s,E)),B.push(c(s,E));continue}te(E,k,h,A),g(E,E),p(E,E,H),d(D,s,E),q=[D[0],D[1]],(n<=1||y(G,q)>R)&&(z.push(q),G=q),l(O,s,E),J=[O[0],O[1]],(n<=1||y(K,J)>R)&&(B.push(J),K=J),V=a,W=h}let X=[e[0].point[0],e[0].point[1]],Z=e.length>1?[e[e.length-1].point[0],e[e.length-1].point[1]]:c(e[0].point,[1,1]),Q=[],$=[];if(e.length===1){if(!(I||L)||x)return k(X,U||H)}else{I||L&&e.length===1||(S?Q.push(...A(X,B[0],13)):Q.push(...j(X,z[0],B[0])));let t=h(s(e[e.length-1].vector));L||I&&e.length===1?$.push(Z):T?$.push(...M(Z,t,H,29)):$.push(...ne(Z,t,H))}return z.concat($,B.reverse(),Q)}const F=[0,0];function I(e){return e!=null&&e>=0}function L(e,t={}){let{streamline:i=.5,size:a=16,last:o=!1}=t;if(e.length===0)return[];let s=.15+(1-i)*.85,l=Array.isArray(e[0])?e:e.map(({x:e,y:t,pressure:r=n})=>[e,t,r]);if(l.length===2){let e=l[1];l=l.slice(0,-1);for(let t=1;t<5;t++)l.push(w(l[0],e,t/4))}l.length===1&&(l=[...l,[...c(l[0],r),...l[0].slice(2)]]);let u=[{point:[l[0][0],l[0][1]],pressure:I(l[0][2])?l[0][2]:.25,vector:[...r],distance:0,runningLength:0}],f=!1,p=0,m=u[0],h=l.length-1;for(let e=1;e<l.length;e++){let t=o&&e===h?[l[e][0],l[e][1]]:w(m.point,l[e],s);if(_(m.point,t))continue;let r=x(t,m.point);if(p+=r,e<h&&!f){if(p<a)continue;f=!0}d(F,m.point,t),m={point:t,pressure:I(l[e][2])?l[e][2]:n,vector:b(F),distance:r,runningLength:p},u.push(m)}return u[0].vector=u[1]?.vector||[0,0],u}function R(e,t={}){return P(L(e,t),t)}var z=R;return {getStroke:R};
  })();
  var NS = "http://www.w3.org/2000/svg";
  var reduced = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  var count = { mark: 0, note: 0 }, uid = 0;

  // Seeded random so a mark looks the same every time the same element is drawn.
  function rng(seedStr) {
    var h = 2166136261;
    for (var i = 0; i < seedStr.length; i++) { h ^= seedStr.charCodeAt(i); h = Math.imul(h, 16777619); }
    return function () { h ^= h << 13; h ^= h >>> 17; h ^= h << 5; return ((h >>> 0) % 10000) / 10000; };
  }
  function outline(points, size, thin) {
    var o = PF.getStroke(points, { size: size, thinning: thin == null ? 0.55 : thin, smoothing: 0.6, streamline: 0.45, simulatePressure: true,
      start: { taper: size * 2.2, cap: true }, end: { taper: size * 3, cap: true } });
    if (!o.length) return "";
    var d = "M" + o[0][0].toFixed(1) + " " + o[0][1].toFixed(1);
    for (var i = 1; i < o.length; i++) {
      var a = o[i], b = o[(i + 1) % o.length];
      d += " Q" + a[0].toFixed(1) + " " + a[1].toFixed(1) + " " + ((a[0] + b[0]) / 2).toFixed(1) + " " + ((a[1] + b[1]) / 2).toFixed(1);
    }
    return d + "Z";
  }
  function centerline(points) {
    var d = "M" + points[0][0].toFixed(1) + " " + points[0][1].toFixed(1);
    for (var i = 1; i < points.length; i++) d += " L" + points[i][0].toFixed(1) + " " + points[i][1].toFixed(1);
    return d;
  }
  function host(el) {
    var cs = getComputedStyle(el);
    if (cs.position === "static") el.style.position = "relative";
    if (cs.display === "inline") el.style.display = "inline-block";
    el.classList.add("ds-mark-host");
    var old = el.querySelectorAll(":scope > .ds-mark");
    for (var i = 0; i < old.length; i++) old[i].remove();
  }
  // Draw: the filled pen outline is revealed by a mask stroke that runs along the centerline.
  function draw(el, strokes, box, opts) {
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "ds-mark");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("viewBox", box.x + " " + box.y + " " + box.w + " " + box.h);
    svg.setAttribute("width", box.w); svg.setAttribute("height", box.h);
    svg.style.left = box.x + "px"; svg.style.top = box.y + "px";
    svg.style.color = opts.color || "var(--mark)";
    if (opts.behind) svg.style.zIndex = "-1";
    var defs = document.createElementNS(NS, "defs"); svg.appendChild(defs);
    var delay = opts.delay || 0, anims = [];
    strokes.forEach(function (s) {
      var id = "ds-mk-" + (++uid);
      var mask = document.createElementNS(NS, "mask"); mask.setAttribute("id", id); mask.setAttribute("maskUnits", "userSpaceOnUse");
      mask.setAttribute("x", String(box.x)); mask.setAttribute("y", String(box.y)); mask.setAttribute("width", String(box.w)); mask.setAttribute("height", String(box.h));
      var mp = document.createElementNS(NS, "path");
      mp.setAttribute("d", centerline(s.pts)); mp.setAttribute("fill", "none"); mp.setAttribute("stroke", "#fff");
      mp.setAttribute("stroke-width", String(s.size * 3.2)); mp.setAttribute("stroke-linecap", "round"); mp.setAttribute("stroke-linejoin", "round");
      mask.appendChild(mp); defs.appendChild(mask);
      var p = document.createElementNS(NS, "path"); p.setAttribute("d", outline(s.pts, s.size, s.thin)); p.setAttribute("mask", "url(#" + id + ")");
      if (s.opacity) p.setAttribute("opacity", String(s.opacity));
      svg.appendChild(p);
      anims.push({ mp: mp, dur: s.dur || 520 });
    });
    el.appendChild(svg);
    if (!reduced && !opts.still && mpSupportsAnim()) {
      anims.forEach(function (a) {
        var len = a.mp.getTotalLength ? a.mp.getTotalLength() : 400;
        a.mp.style.strokeDasharray = len + " " + (len + 10);
        a.mp.style.strokeDashoffset = String(len);
        a.mp.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
          { duration: a.dur, delay: delay, easing: "cubic-bezier(0.45, 0.05, 0.25, 1)", fill: "forwards" });
        delay += a.dur * 0.85;
      });
    }
    return svg;
  }
  function mpSupportsAnim() { return typeof Element.prototype.animate === "function"; }
  function tally(kind) {
    count[kind === "note" ? "note" : "mark"]++;
    if (count.note > 1) console.warn("marks.js: more than one hand note on this screen. The rule is one.");
    // Section-head pen strokes (.ds-section-head--pen, gaps2) are marks too.
    var pens = document.querySelectorAll(".ds-section-head--pen").length;
    if (count.mark + pens > 3) console.warn("marks.js: more than three marks on this screen (" + count.mark + " drawn, " + pens + " section strokes). The rule is three.");
  }
  function size(el) { return { w: el.offsetWidth, h: el.offsetHeight }; }

  var Marks = {
    circle: function (el, opts) {
      opts = opts || {}; host(el); tally("mark");
      var r = rng("c" + (el.textContent || "") + (opts.seed || "")), s = size(el);
      var cx = s.w / 2, cy = s.h / 2, rx = s.w / 2 + 9 + r() * 4, ry = s.h / 2 + 6 + r() * 3;
      var a0 = -Math.PI * (0.62 + r() * 0.1), sweep = Math.PI * 2.16, n = 46, pts = [], tilt = (r() - 0.5) * 0.12;
      for (var i = 0; i <= n; i++) {
        var t = i / n, a = a0 + sweep * t, wob = 1 + (r() - 0.5) * 0.05 + t * 0.07;
        var x = Math.cos(a) * rx * wob, y = Math.sin(a) * ry * wob;
        pts.push([cx + x * Math.cos(tilt) - y * Math.sin(tilt), cy + x * Math.sin(tilt) + y * Math.cos(tilt), 0.5]);
      }
      var pad = 16, sz = opts.size || 3.6;
      return draw(el, [{ pts: pts, size: sz, dur: 680 }], { x: -rx + cx - pad - s.w / 2 + s.w / 2 - 6, y: cy - ry - pad, w: rx * 2 + pad * 2 + 12, h: ry * 2 + pad * 2 }, opts);
    },
    underline: function (el, opts) {
      opts = opts || {}; host(el); tally("mark");
      var r = rng("u" + (el.textContent || "") + (opts.seed || "")), s = size(el);
      var y = s.h + 3 + (opts.offset || 0), x0 = -3, x1 = s.w + 4, n = 18, pts = [];
      for (var i = 0; i <= n; i++) { var t = i / n; pts.push([x0 + (x1 - x0) * t, y + Math.sin(t * Math.PI * (1.2 + r() * 0.5)) * (1.4 + r()) - t * 2.2, 0.5]); }
      var sz = opts.size || 3.4;
      return draw(el, [{ pts: pts, size: sz, dur: 460 }], { x: -10, y: y - 12, w: s.w + 24, h: 24 }, opts);
    },
    scribble: function (el, opts) {
      opts = opts || {}; host(el); tally("mark"); el.style.isolation = "isolate";
      var r = rng("s" + (el.textContent || "")), s = size(el);
      var top = s.h * 0.38, bot = s.h * 0.95, pts = [], x = -4, step = 7 + r() * 2, up = true;
      while (x < s.w + 4) { pts.push([x, (up ? top : bot) + (r() - 0.5) * 3, 0.5]); x += step; up = !up; }
      return draw(el, [{ pts: pts, size: opts.size || 5.5, thin: 0.2, dur: 520, opacity: 0.42 }], { x: -12, y: -6, w: s.w + 24, h: s.h + 12 }, Object.assign({ behind: true }, opts));
    },
    arc: function (el, opts) {
      // A curved arrow that lands on the left or top of el.
      opts = opts || {}; host(el); tally("mark");
      var s = size(el), side = opts.side || "left", r = rng("a" + (el.textContent || ""));
      var end = side === "left" ? [-8, s.h / 2] : [s.w / 2, -8];
      var start = side === "left" ? [-58, s.h / 2 - 34 - r() * 8] : [s.w / 2 - 50, -50];
      var ctrl = side === "left" ? [-60 + r() * 6, s.h / 2 + 4] : [s.w / 2 - 58, -6];
      var pts = [], n = 22;
      for (var i = 0; i <= n; i++) { var t = i / n, u = 1 - t; pts.push([u * u * start[0] + 2 * u * t * ctrl[0] + t * t * end[0], u * u * start[1] + 2 * u * t * ctrl[1] + t * t * end[1], 0.5]); }
      var ang = Math.atan2(end[1] - pts[n - 3][1], end[0] - pts[n - 3][0]);
      function head(da) { var a = ang + Math.PI + da; return [[end[0], end[1], 0.6], [end[0] + Math.cos(a) * 6, end[1] + Math.sin(a) * 6, 0.5], [end[0] + Math.cos(a) * 12, end[1] + Math.sin(a) * 12, 0.4]]; }
      return draw(el, [{ pts: pts, size: 2.8, dur: 480 }, { pts: head(0.55), size: 2.8, dur: 140 }, { pts: head(-0.55), size: 2.8, dur: 140 }],
        { x: Math.min(start[0], ctrl[0]) - 16, y: Math.min(start[1], end[1]) - 16, w: Math.abs(end[0] - Math.min(start[0], ctrl[0])) + 40, h: Math.abs(Math.max(end[1], ctrl[1]) - Math.min(start[1], end[1])) + 40 }, opts);
    },
    pen: function (el, opts) {
      // The active tab's pen line. Static after its first draw. Does not count toward the three.
      opts = opts || {}; host(el);
      var s = size(el), w = Math.min(36, s.w * 0.5), x0 = (s.w - w) / 2, y = s.h - 6, pts = [];
      for (var i = 0; i <= 10; i++) { var t = i / 10; pts.push([x0 + w * t, y + Math.sin(t * Math.PI) * 1.2 - t * 1.5, 0.5]); }
      return draw(el, [{ pts: pts, size: 3.2, dur: 300 }], { x: x0 - 8, y: y - 10, w: w + 16, h: 20 }, Object.assign({ color: "var(--mark-green)" }, opts));
    },
    note: function (el, text, opts) {
      opts = opts || {}; tally("note");
      var n = document.createElement("span");
      n.className = "ds-hand ds-note" + (opts.cls ? " " + opts.cls : "");
      n.textContent = text; n.setAttribute("aria-hidden", "true");
      if (opts.color) n.style.color = opts.color;
      el.appendChild(n);
      if (!reduced && n.animate) n.animate([{ opacity: 0, transform: "translateY(4px) rotate(-6deg)" }, { opacity: 1, transform: "rotate(-4deg)" }],
        { duration: 420, delay: opts.delay || 0, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "backwards" });
      return n;
    },
    reset: function () { count = { mark: 0, note: 0 }; }
  };
  window.Marks = Marks;
})();
