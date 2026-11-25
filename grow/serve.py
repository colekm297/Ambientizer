#!/usr/bin/env python3
"""Static server for Grow. No cache. Usage: python3 serve.py [port] [host]
POST /__save?name=x.wav writes the body into renders/ (localhost only, used by the render check)."""
import http.server, os, re, sys
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5071
HOST = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()
    def do_POST(self):
        u = urlparse(self.path)
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
