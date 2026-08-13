"""Einfacher HTTP-Server fuer das Paper-Trader Dashboard.

Generiert das Dashboard bei jedem Aufruf neu aus der Datenbank.

Aufruf: uv run python server.py [--port 8080] [--db-pfad paper.db]
"""

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer

from dashboard import erstelle_dashboard


class DashboardHandler(BaseHTTPRequestHandler):
    db_pfad: str = "paper.db"

    def do_GET(self):
        if self.path not in ("/", "/dashboard"):
            self.send_error(404)
            return

        try:
            html_pfad = erstelle_dashboard(db_pfad=self.db_pfad, ausgabe="/tmp/dashboard.html")
            with open(html_pfad, "rb") as f:
                inhalt = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(inhalt)))
            self.end_headers()
            self.wfile.write(inhalt)
        except Exception as e:
            self.send_error(500, str(e))

    def log_message(self, format, *args):
        pass  # Kein Log-Spam


def main():
    parser = argparse.ArgumentParser(description="Paper-Trader Dashboard-Server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db-pfad", default="paper.db")
    args = parser.parse_args()

    DashboardHandler.db_pfad = args.db_pfad

    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"Dashboard läuft auf http://0.0.0.0:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
