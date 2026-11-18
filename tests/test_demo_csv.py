"""End-to-end CSV fixture smoke test for the local file validator."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

from warehouse_validator.validator import validate_file

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "warehouse_receiving_demo.csv"


class DemoCSVTests(unittest.TestCase):
    def test_actual_csv_file_classification(self):
        report = validate_file(DEMO)
        self.assertEqual(report["summary"], {
            "total": 8, "ok": 4, "review_required": 4
        })
        self.assertEqual(
            [r["status"] for r in report["records"]],
            ["OK", "REVIEW_REQUIRED", "OK", "REVIEW_REQUIRED",
             "REVIEW_REQUIRED", "REVIEW_REQUIRED", "OK", "OK"]
        )
        self.assertEqual(report["records"][1]["missing_fields"], ["quantity"])
        self.assertEqual(report["records"][3]["errors"], ["quantity_must_be_positive_integer"])
        self.assertEqual(report["records"][4]["errors"], ["quantity_must_be_positive_integer"])
        self.assertEqual(report["records"][5]["missing_fields"], ["supplier"])
        self.assertEqual(report["records"][6]["quantity"], 250)

    def test_cli_reads_actual_csv(self):
        run = subprocess.run(
            [sys.executable, "-m", "warehouse_validator.validator", str(DEMO)],
            capture_output=True, text=True, cwd=ROOT, check=True
        )
        report = json.loads(run.stdout)
        self.assertEqual(report["source_type"], "csv")
        self.assertEqual(report["summary"]["ok"], 4)
        self.assertEqual(report["summary"]["review_required"], 4)


if __name__ == "__main__":
    unittest.main()
