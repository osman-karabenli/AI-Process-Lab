import io
import json
import tempfile
import unittest
from pathlib import Path

from warehouse_validator.n8n_client import (
    validate_webhook_url, send_report, main,
)
from warehouse_validator.validator import ValidationError, validate_file


class _FakeOpener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout=0):
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append((request, timeout, payload))
        record = payload["record"]
        body = {
            "record_id": record["record_id"],
            "status": record["status"],
            "inserted": True,
        }

        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(body).encode("utf-8")
        return Response()


class N8NClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / "demo.csv"
        self.file.write_text(
            "supplier,material,quantity\nBosch,Motor A12,100\nSiemens,Sensor B25,\n",
            encoding="utf-8"
        )

    def test_valid_url(self):
        self.assertEqual(
            validate_webhook_url("http://127.0.0.1:5678/webhook-test/warehouse-receiving-v1"),
            "http://127.0.0.1:5678/webhook-test/warehouse-receiving-v1",
        )

    def test_remote_http_rejected(self):
        with self.assertRaises(ValidationError):
            validate_webhook_url("http://public.example.com/webhook/warehouse-receiving-v1")

    def test_other_webhook_path_rejected(self):
        with self.assertRaises(ValidationError):
            validate_webhook_url("https://n8n.example.com/webhook/delete-everything")

    def test_url_with_credentials_rejected(self):
        with self.assertRaises(ValidationError):
            validate_webhook_url("https://user:secret@n8n.example.com/webhook/warehouse-receiving-v1")

    def test_token_required(self):
        with self.assertRaises(ValidationError):
            send_report(validate_file(self.file),
                        "http://localhost:5678/webhook-test/warehouse-receiving-v1",
                        "short",
                        opener=_FakeOpener())

    def test_records_sent_individually(self):
        opener = _FakeOpener()
        result = send_report(
            validate_file(self.file),
            "http://127.0.0.1:5678/webhook-test/warehouse-receiving-v1",
            "some-long-random-development-token",
            opener=opener,
        )
        self.assertEqual(len(opener.requests), 2)
        self.assertTrue(all(x["inserted"] for x in result))
        self.assertEqual(opener.requests[0][2]["record"]["supplier"], "Bosch")
        self.assertEqual(opener.requests[1][2]["record"]["missing_fields"], ["quantity"])
        self.assertEqual(opener.requests[0][1], 20)
        self.assertEqual(opener.requests[0][0].get_method(), "POST")
        self.assertEqual(
            opener.requests[0][0].get_header("X-warehouse-token"),
            "some-long-random-development-token",
        )

    def test_default_is_dry_run(self):
        self.assertEqual(main([str(self.file)]), 0)


if __name__ == "__main__":
    unittest.main()
