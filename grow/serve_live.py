#!/usr/bin/env python3
"""Cole's copy of Grow: read-only static files from ./site, 127.0.0.1 only, no directory listing."""
import http.server, os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def end_headers(self):
        fixed = self.path.startswith(("/sounds/", "/ds/fonts/"))
        self.send_header("Cache-Control", "private, max-age=2592000" if fixed else "no-cache")
        super().end_headers()
    def list_directory(self, path):
        self.send_error(404)
    def log_message(self, *a): pass

H.extensions_map.update({".js": "text/javascript", ".flac": "audio/flac", ".svg": "image/svg+xml", ".woff2": "font/woff2"})
if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", 5070), H).serve_forever()
