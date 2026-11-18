"""Deterministic tests: no Docker, n8n or network access required."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from warehouse_validator.validator import (ValidationError, parse_labeled_document_text,
                                           validate_file, validate_record)


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)

    def write(self, filename, text):
        path = self.directory / filename
        path.write_text(text, encoding="utf-8")
        return path

    def test_csv_ok_and_missing(self):
        result = validate_file(self.write("in.csv", "supplier,material,quantity\nBosch,Motor A12,100\nSiemens,Sensor B25,\nABB,Kabel C30,50\n"))
        self.assertEqual(result["summary"], {"total": 3, "ok": 2, "review_required": 1})
        self.assertEqual(result["records"][1]["missing_fields"], ["quantity"])

    def test_supplier_missing(self):
        record = validate_record({"supplier": "", "material": "Part", "quantity": 1}, "id")
        self.assertIn("supplier", record["missing_fields"])
        self.assertEqual(record["status"], "REVIEW_REQUIRED")

    def test_invalid_quantity(self):
        for raw in ("abc", "-2", "0", "2.5", "1,000"):
            with self.subTest(raw=raw):
                self.assertEqual(validate_record({"supplier": "S", "material": "M", "quantity": raw}, "id")["status"], "REVIEW_REQUIRED")

    def test_missing_quantity_is_not_invented(self):
        record = validate_record({"supplier": "S", "material": "M", "quantity": ""}, "id")
        self.assertIsNone(record["quantity"])
        self.assertEqual(record["errors"], [])
        self.assertEqual(record["missing_fields"], ["quantity"])

    def test_semicolon_delimiter_and_german_columns(self):
        result = validate_file(self.write("de.csv", "Lieferant;Artikel;Menge\nBosch;Motor;10\n"))
        self.assertEqual(result["records"][0]["quantity"], 10)
        self.assertEqual(result["summary"]["ok"], 1)

    def test_utf8_bom(self):
        path = self.write("utf8.csv", "supplier,material,quantity\nMüller GmbH,Bolzen,1\n")
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assertEqual(validate_file(path)["summary"]["ok"], 1)

    def test_missing_csv_column(self):
        path = self.write("in.csv", "supplier,material\nBosch,Motor\n")
        with self.assertRaisesRegex(ValidationError, "quantity"):
            validate_file(path)

    def test_blank_csv(self):
        with self.assertRaisesRegex(ValidationError, "empty"):
            validate_file(self.write("empty.csv", ""))

    def test_extra_csv_values_rejected(self):
        path = self.write("extra.csv", "supplier,material,quantity\nS,M,1,extra\n")
        with self.assertRaisesRegex(ValidationError, "more values"):
            validate_file(path)

    def test_duplicate_id_same_file(self):
        path = self.write("a.csv", "supplier,material,quantity\nA,B,10\n")
        one = validate_file(path)["records"][0]["record_id"]
        two = validate_file(path)["records"][0]["record_id"]
        self.assertEqual(one, two)

    def test_document_always_requires_review(self):
        records = parse_labeled_document_text("Lieferant: Bosch\nArtikel: Schraube\nMenge: 8", b"document")
        self.assertEqual(records[0]["status"], "REVIEW_REQUIRED")
        self.assertEqual(records[0]["missing_fields"], [])
        self.assertIn("document_extraction_requires_manual_verification", records[0]["review_reasons"])

    def test_document_missing_fields(self):
        record = parse_labeled_document_text("Supplier: Bosch", b"doc")[0]
        self.assertEqual(record["missing_fields"], ["material", "quantity"])

    def test_unsupported_extension(self):
        with self.assertRaisesRegex(ValidationError, "Supported"):
            validate_file(self.write("unsafe.txt", "anything"))

    def test_image_path_uses_extracted_text(self):
        path = self.write("image.png", "fake binary")
        with patch("warehouse_validator.validator._read_image", return_value="Supplier: Bosch\nMaterial: Motor\nQuantity: 2"):
            self.assertEqual(validate_file(path)["summary"]["review_required"], 1)

    def test_pdf_path_uses_extracted_text(self):
        path = self.write("document.pdf", "fake binary")
        with patch("warehouse_validator.validator._read_pdf", return_value="Supplier: Bosch\nMaterial: Motor\nQuantity: 2"):
            self.assertEqual(validate_file(path)["summary"]["review_required"], 1)

    def test_empty_data_rows(self):
        path = self.write("empty.csv", "supplier,material,quantity\n,,\n")
        with self.assertRaisesRegex(ValidationError, "data rows"):
            validate_file(path)


if __name__ == "__main__":
    unittest.main()
