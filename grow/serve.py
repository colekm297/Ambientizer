#!/usr/bin/env python3
"""Static server for Grow. No cache. Usage: python3 serve.py [port] [host]
POST /__save?name=x.wav writes the body into renders/ (localhost only, used by the render check).
POST /api/scene/ask (localhost only): Scene's select-and-ask tool. Asks Claude Fable 5.2 for 3 draw() variants (Gemini Flash if that fails), logs spend."""
import http.server, json, os, re, sys, time, urllib.request, urllib.error
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5071
HOST = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"

REPO = os.environ.get("SCENE_REPO") or os.path.dirname(ROOT)
SPEND = os.path.join(REPO, "data", "spend.jsonl")
FABLE_MODEL = "claude-fable-5-2"
FABLE_MAX_OUT = 6000         # output tokens per call, thinking included
FABLE_IN, FABLE_OUT = 8.00, 40.00   # $ per million tokens, Claude Fable 5.2 list price (claude-api skill table, cached 2026-11-03)
ASK_MODEL = os.environ.get("SCENE_ASK_MODEL", "gemini-3.8-flash")  # fallback: newest Flash in the models list on 2026-11-26
ASK_MAX_OUT = 10000          # output tokens per call, thinking included
ASK_DAILY_CAP = float(os.environ.get("SCENE_ASK_DAILY_CAP", "3.00"))  # dollars per day, this endpoint only
# Estimated list price per million tokens (Flash tier). The API returns tokens, not dollars, so this is an estimate.
PRICE_IN, PRICE_OUT = 0.50, 3.00
BANNED = re.compile(r"\b(eval|arguments|constructor|__proto__|prototype|import|require|process|Reflect|Proxy|WebAssembly|globalThis|self|window|document|fetch|XMLHttpRequest|WebSocket|localStorage|sessionStorage|indexedDB|navigator|location|Worker|importScripts|setTimeout|setInterval|Function)\b|\[\s*['\"`]")

def gemini_key():
    k = os.environ.get("GEMINI_API_KEY")
    if k: return k
    try:
        for line in open(os.path.join(REPO, ".env")):
            m = re.match(r"\s*(?:export\s+)?GEMINI_API_KEY\s*=\s*(.*)\s*$", line)
            if m: return m.group(1).strip().strip("'\"")
    except OSError:
        pass
    return None

def spent_today():
    day, tot = time.strftime("%Y-%m-%d"), 0.0
    try:
        for line in open(SPEND):
            if '"scene ask"' in line and day in line[:20]:
                try: tot += float(json.loads(line).get("est_cost", 0))
                except ValueError: pass
    except OSError:
        pass
    return tot

SYSTEM = """You write small Canvas 2D programs that add one element to a code-drawn painting of a desert world at dusk (1280x720 scene pixels, origin top-left). A person selected a region and typed a request. Return 3 variants that differ in shape, composition or style, not only in color.

Each variant is the BODY of a function draw(ctx, t, p, box, e). Write statements only, no function wrapper, no return value.
- ctx: Canvas 2D context in scene pixel coordinates, already clipped to the person's mask. Anything outside the mask is cut off, so draw to fill and blend into the region, with soft edges where it meets the picture.
- t: seconds on the scene clock, always increasing. Animate with t (slow drift, shimmer, flow, light moving). The element must loop smoothly: use sin/cos of t or fractions of t, never accumulate state.
- p: slider values by name, for example p.height. Declare 2 to 4 params, each {name, label, min, max, value}. name is a plain identifier, label is 1 or 2 words in Title Case, value sits between min and max. Params must visibly change the result.
- box: {x, y, w, h, cx, cy} in scene pixels, the bounding box of the mask. Lay the element out relative to box so it fits the selection.
- e: {lift, night, time, col, rgba, sun, rnd}. e.lift is 0 normally and rises to about 0.25 during a music refrain: use it to brighten or intensify. e.night is 0 to 1, how dark it is. e.col is an object of CSS color strings: top, mid, hor, sun, glow, far, cliff, lit, near, haze, rim, shade. e.rgba(name, alpha) returns that color with an alpha. e.sun is {x, y} in scene pixels, the main light source, so put highlights on the side facing it and shadows opposite. e.rnd(i) is a deterministic random number 0..1 for integer i. Never use Math.random.
- Use the palette in e.col so the element matches the time of day. Rock and sand use cliff, lit, shade, near, far. Light uses rim, glow, sun. Water or mist uses haze and mid.

Performance: draw runs every frame at 60 fps and must take under 3 ms. Loops under 300 iterations, no shadowBlur, no filter, no more than 12 gradients per call, no per-frame allocation of big arrays. If the result is slow it is switched off.

Safety: only ctx, t, p, box, e and Math exist. Do not use window, document, fetch, eval, Function, constructor, import, setTimeout, localStorage, or computed string property access like obj["x"].

Quality: make it look painted and believable, with layered shapes, gradients, texture, and light and shadow from the sun, like a matte painting, not clip art. Keep shapes organic, not perfectly geometric. Never fill the whole box with a flat rectangle.

If the input includes "refine", it holds the current code and params of an existing element. Return 3 revised versions that apply the new request while keeping what already works.

Variant name: 1 or 2 words. Return only JSON that matches the schema."""

SCHEMA = {"type": "OBJECT", "properties": {"variants": {"type": "ARRAY", "minItems": 3, "maxItems": 3, "items": {"type": "OBJECT", "properties": {
    "name": {"type": "STRING"}, "code": {"type": "STRING"},
    "params": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"name": {"type": "STRING"}, "label": {"type": "STRING"}, "min": {"type": "NUMBER"}, "max": {"type": "NUMBER"}, "value": {"type": "NUMBER"}}, "required": ["name", "label", "min", "max", "value"]}}},
    "required": ["name", "code", "params"]}}}, "required": ["variants"]}

SCHEMA_JSON = {"type": "object", "additionalProperties": False, "required": ["variants"], "properties": {"variants": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["name", "code", "params"], "properties": {"name": {"type": "string"}, "code": {"type": "string"},
    "params": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "label", "min", "max", "value"],
        "properties": {"name": {"type": "string"}, "label": {"type": "string"}, "min": {"type": "number"}, "max": {"type": "number"}, "value": {"type": "number"}}}}}}}}}

def clean_variants(raw):
    out = []
    for v in raw.get("variants", [])[:3]:
        code = str(v.get("code", ""))
        if not code.strip() or len(code) > 8000 or BANNED.search(code): continue
        params = []
        for q in v.get("params", [])[:6]:
            try:
                n = str(q["name"])
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,23}", n): continue
                lo, hi = float(q["min"]), float(q["max"])
                if not hi > lo: continue
                val = min(hi, max(lo, float(q["value"])))
                params.append({"name": n, "label": str(q.get("label", n))[:20], "min": lo, "max": hi, "value": val})
            except (KeyError, TypeError, ValueError):
                continue
        out.append({"name": str(v.get("name", "Element"))[:24], "code": code, "params": params})
    return out

def anthropic_key():
    k = os.environ.get("ANTHROPIC_API_KEY")
    if k: return k
    try:
        for line in open(os.path.join(REPO, ".env")):
            m = re.match(r"\s*(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*(.*)\s*$", line)
            if m: return m.group(1).strip().strip("'\"")
    except OSError:
        pass
    return None

def log_spend(model, tin, tout, cost, req, extra=None):
    row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "what": "scene ask", "model": model, "input_tokens": tin, "output_tokens": tout, "est_cost": cost, "request": req[:80]}
    row.update(extra or {})
    try:
        os.makedirs(os.path.dirname(SPEND), exist_ok=True)
        with open(SPEND, "a") as f: f.write(json.dumps(row) + "\n")
    except OSError:
        pass

def post_json(url, headers, payload, timeout=180):
    r = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", **headers})
    return json.load(urllib.request.urlopen(r, timeout=timeout))

def ask_fable(text, req):
    """Claude Fable 5.2 over the Messages API (raw HTTP: this server is stdlib-only and the SDK is not installed).
    Thinking is always on for this model, so max_tokens covers thinking plus the 3 variants. Returns variants or raises."""
    key = anthropic_key()
    if not key: raise RuntimeError("no Anthropic key")
    payload = {"model": FABLE_MODEL, "max_tokens": FABLE_MAX_OUT, "system": SYSTEM,
               "messages": [{"role": "user", "content": text}],
               "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA_JSON}}}
    d = post_json("https://api.anthropic.com/v1/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"}, payload)
    u = d.get("usage", {})
    tin = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    tout = u.get("output_tokens", 0)
    cost = round((tin * FABLE_IN + tout * FABLE_OUT) / 1e6, 4)
    log_spend(FABLE_MODEL, tin, tout, cost, req, {"stop": d.get("stop_reason")})
    if d.get("stop_reason") != "end_turn": raise RuntimeError(f"stop_reason {d.get('stop_reason')}")
    out = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    variants = clean_variants(json.loads(out))
    if not variants: raise RuntimeError("no usable variants")
    return variants, FABLE_MODEL, tin, tout, cost

def ask_gemini(text, req):
    key = gemini_key()
    if not key: raise RuntimeError("no Gemini key")
    payload = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
               "contents": [{"role": "user", "parts": [{"text": text}]}],
               "generationConfig": {"maxOutputTokens": ASK_MAX_OUT, "temperature": 1.0, "responseMimeType": "application/json", "responseSchema": SCHEMA}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{ASK_MODEL}:generateContent"
    d = None
    for level in ("low", None):  # a model that rejects thinkingLevel gets a plain retry (a 400 is not billed)
        pl = json.loads(json.dumps(payload))
        if level: pl["generationConfig"]["thinkingConfig"] = {"thinkingLevel": level}
        try:
            d = post_json(url, {"x-goog-api-key": key}, pl, 120); break
        except urllib.error.HTTPError as e:
            if e.code == 400 and level: continue
            raise
    um = d.get("usageMetadata", {})
    tin, tout = um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0)
    cost = round((tin * PRICE_IN + tout * PRICE_OUT) / 1e6, 4)
    log_spend(ASK_MODEL, tin, tout, cost, req)
    variants = clean_variants(json.loads(d["candidates"][0]["content"]["parts"][-1]["text"]))
    if not variants: raise RuntimeError("no usable variants")
    return variants, ASK_MODEL, tin, tout, cost

def scene_ask(body):
    req = str(body.get("request", "")).strip()[:300]
    if not req: return 400, {"error": "Type a request."}
    if spent_today() >= ASK_DAILY_CAP: return 429, {"error": "Daily Ask limit reached."}
    ctx = {k: body.get(k) for k in ("request", "bbox", "box", "mask", "layers", "palette", "time", "timeName", "elements", "anchors", "refine")}
    ctx["request"] = req
    text = json.dumps(ctx)[:30000]
    fell = None
    for name, fn in (("fable", ask_fable), ("gemini", ask_gemini)):
        try:
            variants, model, tin, tout, cost = fn(text, req)
            return 200, {"variants": variants, "model": model, "fallback": fell, "tokens": {"in": tin, "out": tout}, "cost": cost}
        except Exception as e:
            fell = f"{name}: {str(e)[:120]}"
            print("scene ask", fell, file=sys.stderr)
    return 502, {"error": "No model returned usable code.", "detail": fell}

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()
    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/scene/ask":
            if self.client_address[0] not in ("127.0.0.1", "::1"): self.send_error(404); return
            n = int(self.headers.get("Content-Length", 0))
            if n > 120000: self.send_error(413); return
            try: code, out = scene_ask(json.loads(self.rfile.read(n) or b"{}"))
            except ValueError: code, out = 400, {"error": "Bad request."}
            data = json.dumps(out).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        if u.path != "/__save" or self.client_address[0] not in ("127.0.0.1", "::1"):
            self.send_error(404); return
        name = re.sub(r"[^A-Za-z0-9._-]", "_", parse_qs(u.query).get("name", ["x.bin"])[0])
        n = int(self.headers.get("Content-Length", 0))
        os.makedirs(os.path.join(ROOT, "renders"), exist_ok=True)
        with open(os.path.join(ROOT, "renders", name), "wb") as f:
            left = n
            while left > 0:
                b = self.rfile.read(min(1 << 20, left))
                if not b: break
                f.write(b); left -= len(b)
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

if __name__ == "__main__":
    H.extensions_map.update({".js": "text/javascript", ".mjs": "text/javascript", ".wav": "audio/wav", ".svg": "image/svg+xml"})
    http.server.ThreadingHTTPServer((HOST, PORT), H).serve_forever()
