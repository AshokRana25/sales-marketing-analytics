import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from marketlens.pipeline import initialize
from marketlens.server import make_handler


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Path(self.temp.name) / "api.db"
        initialize(database)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(database))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        client.request(method, path, body, headers or {})
        response = client.getresponse()
        status, data, response_headers = response.status, response.read(), dict(response.getheaders())
        client.close()
        return status, data, response_headers

    def test_dashboard_and_security_headers(self):
        status, data, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"MarketLens", data)
        self.assertIn("Content-Security-Policy", headers)

    def test_path_traversal_is_not_served(self):
        self.assertEqual(self.request("GET", "/../marketlens/pipeline.py")[0], 404)

    def test_import_and_report(self):
        text = "order_id,date,channel,campaign,gross_revenue,refund_amount,currency\nSYN-1,2026-08-01,email,Launch,100,0,USD\n"
        status, data, _ = self.request("POST", "/api/import", json.dumps({"sales_csv": text}),
                                       {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["accepted"], 1)
        self.assertEqual(json.loads(self.request("GET", "/api/report")[1])["summary"]["net_revenue"], 100)

    def test_bad_payloads(self):
        for payload in ["not json", "[]", '{"sales_csv": 12}', "{}"]:
            with self.subTest(payload=payload):
                self.assertEqual(self.request("POST", "/api/import", payload,
                    {"Content-Type": "application/json"})[0], 400)

    def test_content_type_and_body_size_limits(self):
        self.assertEqual(self.request("POST", "/api/import", "{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/import", "{}",
            {"Content-Type": "application/json", "Content-Length": "2000001"})[0], 413)

    def test_invalid_filter_returns_400(self):
        self.assertEqual(self.request("GET", "/api/report?start=bad-date")[0], 400)

    def test_export_has_attachment_headers(self):
        status, data, headers = self.request("GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("text/csv", headers["Content-Type"])
        self.assertTrue(data.decode("utf-8-sig").startswith("campaign,channel,"))


if __name__ == "__main__":
    unittest.main()
