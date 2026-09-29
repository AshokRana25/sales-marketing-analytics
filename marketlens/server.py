"""Loopback-only development/demo server. No production authentication is claimed."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .analytics import export_csv, report
from .pipeline import connect, import_csv, initialize

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 2_000_000


def make_handler(database):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, data, content_type="application/json; charset=utf-8", attachment=None):
            body = json.dumps(data, allow_nan=False).encode() if isinstance(data, (dict, list)) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlsplit(self.path)
            try:
                if url.path in {"/api/report", "/api/export"}:
                    query = parse_qs(url.query)
                    result = report(database, query.get("start", [None])[0],
                                    query.get("end", [None])[0], query.get("channel", [""])[0])
                    if url.path == "/api/export":
                        return self.send(200, export_csv(result), "text/csv; charset=utf-8",
                                         "marketlens-campaigns.csv")
                    return self.send(200, result)
                if url.path == "/api/health":
                    return self.send(200, {"status": "ok", "dataset": "local", "currency": "USD"})
                assets = {"/": ("marketlens/static/index.html", "text/html; charset=utf-8"),
                          "/app.js": ("marketlens/static/app.js", "text/javascript; charset=utf-8"),
                          "/styles.css": ("marketlens/static/styles.css", "text/css; charset=utf-8"),
                          "/samples/sales.csv": ("samples/sales.csv", "text/csv; charset=utf-8"),
                          "/samples/ads.csv": ("samples/ads.csv", "text/csv; charset=utf-8")}
                if url.path in assets:
                    path, mime = assets[url.path]
                    return self.send(200, (ROOT / path).read_bytes(), mime)
                return self.send(404, {"error": "Not found"})
            except ValueError as error:
                return self.send(400, {"error": str(error)})
            except Exception:
                return self.send(500, {"error": "Unable to build report. Check the local database."})

        def do_POST(self):
            if urlsplit(self.path).path != "/api/import":
                return self.send(404, {"error": "Not found"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "Content-Type must be application/json"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > MAX_BODY:
                    return self.send(413, {"error": "Request must contain 1 to 2000000 bytes"})
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                sales, ads = payload.get("sales_csv", ""), payload.get("ads_csv", "")
                if not isinstance(sales, str) or not isinstance(ads, str):
                    raise ValueError("CSV fields must be strings")
                return self.send(200, import_csv(database, sales, ads))
            except (ValueError, UnicodeDecodeError) as error:
                return self.send(400, {"error": str(error)})
            except Exception:
                return self.send(500, {"error": "Import failed; transaction rolled back."})

        def log_message(self, format, *args):
            # Do not write submitted CSV content or query strings to request logs.
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Run the MarketLens local dashboard")
    parser.add_argument("--port", type=int, default=5090)
    parser.add_argument("--database", default="data/marketlens.db")
    parser.add_argument("--empty", action="store_true", help="Do not seed a new database")
    args = parser.parse_args()
    initialize(args.database)
    with connect(args.database) as db:
        first_run = db.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0
    if first_run and not args.empty:
        import_csv(args.database, (ROOT / "samples/sales.csv").read_text(),
                   (ROOT / "samples/ads.csv").read_text())
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.database))
    server.daemon_threads = True
    print(f"MarketLens running at http://127.0.0.1:{args.port} (local demo only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
