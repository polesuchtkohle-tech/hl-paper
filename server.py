"""HTTP-Server fuer das Paper-Trader Dashboard.

Dashboard wird alle 60 Sekunden im Hintergrund neu generiert und gecacht.
Jeder Request bekommt sofort die letzte fertige Version.

Aufruf: uv run python server.py [--port 8080] [--db-pfad paper.db]
"""

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from dashboard import erstelle_dashboard

_cache_lock = threading.Lock()
_cache_html: bytes | None = None


def _refresh_loop(db_pfad: str) -> None:
    global _cache_html
    while True:
        try:
            pfad = erstelle_dashboard(db_pfad=db_pfad, ausgabe="/tmp/dashboard.html")
            with open(pfad, "rb") as f:
                html = f.read()
            with _cache_lock:
                _cache_html = html
        except Exception as e:
            print(f"Cache-Refresh-Fehler: {e}", flush=True)
        time.sleep(60)


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/dashboard"):
            self.send_error(404)
            return

        with _cache_lock:
            inhalt = _cache_html

        if inhalt is None:
            self.send_error(503, "Dashboard wird geladen, bitte in ~60s neu laden.")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(inhalt)))
        self.end_headers()
        try:
            self.wfile.write(inhalt)
        except BrokenPipeError:
            pass

    def log_message(self, format, *args):
        pass  # Kein Log-Spam


def main():
    parser = argparse.ArgumentParser(description="Paper-Trader Dashboard-Server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db-pfad", default="paper.db")
    args = parser.parse_args()

    t = threading.Thread(target=_refresh_loop, args=(args.db_pfad,), daemon=True)
    t.start()
    print(f"Dashboard-Cache wird aufgebaut...", flush=True)

    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"Dashboard läuft auf http://0.0.0.0:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
