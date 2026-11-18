#!/usr/bin/env python3
"""Validate local CSV, PDF, or image-based warehouse receiving records.

CSV data is validated deterministically. Data extracted from documents is ALWAYS
routed for human review. This tool makes no network calls or ERP changes.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS = ("supplier", "material", "quantity")
ALIASES = {
    "supplier": "supplier", "lieferant": "supplier",
    "material": "material", "artikel": "material",
    "quantity": "quantity", "menge": "quantity", "qty": "quantity",
}
LABEL_RE = re.compile(
    r"^\s*(supplier|lieferant|material|artikel|quantity|menge|qty)\s*[:=]\s*(.*?)\s*$",
    re.IGNORECASE,
)
SUPPORTED_EXTENSIONS = {".csv", ".pdf", ".png", ".jpg", ".jpeg"}
MAX_SIZE = 15 * 1024 * 1024
MAX_PDF_PAGES = 10


class ValidationError(Exception):
    """The source cannot be safely parsed with the current rules."""


def _quantity(value):
    """Accept strictly positive whole-unit quantities, without guessing locale."""
    if value is None or str(value).strip() == "":
        return None, None
    raw = str(value).strip()
    if not re.fullmatch(r"[+]?[0-9]+", raw):
        return None, "quantity_must_be_positive_integer"
    amount = int(raw)
    if amount <= 0:
        return None, "quantity_must_be_positive_integer"
    return amount, None


def validate_record(raw, record_id, *, from_document=False):
    """Check one record. Never synthesize missing information."""
    result = {"record_id": record_id}
    missing = []
    errors = []
    for field in ("supplier", "material"):
        value = raw.get(field)
        value = str(value).strip() if value is not None else ""
        result[field] = value or None
        if not value:
            missing.append(field)
    quantity, quantity_error = _quantity(raw.get("quantity"))
    result["quantity"] = quantity
    if raw.get("quantity") is None or str(raw.get("quantity")).strip() == "":
        missing.append("quantity")
    elif quantity_error:
        errors.append(quantity_error)
    review_reasons = []
    if from_document:
        review_reasons.append("document_extraction_requires_manual_verification")
    result.update({
        "status": "REVIEW_REQUIRED" if missing or errors or review_reasons else "OK",
        "missing_fields": missing,
        "errors": errors,
        "review_reasons": review_reasons,
    })
    return result


def _source_id(raw_bytes, row_number):
    digest = hashlib.sha256(raw_bytes).hexdigest()[:16]
    return f"REC-{digest}-{row_number:05d}"


def parse_csv(path, raw_bytes):
    try:
        content = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError("CSV must be UTF-8 encoded (UTF-8 BOM is supported).") from exc
    if not content.strip():
        raise ValidationError("CSV file is empty.")
    try:
        dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(content, newline=""), dialect=dialect)
    if not reader.fieldnames:
        raise ValidationError("CSV has no header row.")
    columns = {}
    for column in reader.fieldnames:
        if column is None:
            continue
        normalized = ALIASES.get(column.strip().lower())
        if normalized:
            if normalized in columns:
                raise ValidationError(f"Duplicate CSV column for '{normalized}'.")
            columns[normalized] = column
    absent = [name for name in REQUIRED_FIELDS if name not in columns]
    if absent:
        raise ValidationError("CSV is missing required columns: " + ", ".join(absent))
    result = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValidationError(f"CSV row {row_number} has more values than the header.")
        if not any(value is not None and str(value).strip() for value in row.values()):
            continue
        raw = {field: row.get(columns[field]) for field in REQUIRED_FIELDS}
        result.append(validate_record(raw, _source_id(raw_bytes, row_number)))
    if not result:
        raise ValidationError("CSV does not contain any data rows.")
    return result


def parse_labeled_document_text(text, raw_bytes):
    """Small initial scope: one delivery note with labeled fields per document."""
    fields = {}
    for line in text.splitlines():
        match = LABEL_RE.match(line)
        if match:
            normalized = ALIASES[match.group(1).lower()]
            if normalized not in fields:
                fields[normalized] = match.group(2)
    return [validate_record(fields, _source_id(raw_bytes, 1), from_document=True)]


def _ocr_image(image):
    try:
        import pytesseract
    except ImportError as exc:
        raise ValidationError("Image reading requires: pip install '.[documents]' and Tesseract OCR.") from exc
    try:
        return pytesseract.image_to_string(image, lang="eng+deu")
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError) as exc:
        raise ValidationError("Tesseract OCR with eng and deu language packs is required.") from exc


def _read_image(path):
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise ValidationError("Image reading requires: pip install '.[documents]'.") from exc
    try:
        with Image.open(path) as image:
            return _ocr_image(image)
    except (OSError, UnidentifiedImageError) as exc:
        raise ValidationError("Image could not be read.") from exc


def _read_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValidationError("PDF reading requires: pip install '.[documents]'.") from exc
    try:
        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted or len(reader.pages) > MAX_PDF_PAGES:
            raise ValidationError("Encrypted PDFs or PDFs with more than 10 pages are not supported.")
        parts = [page.extract_text() or "" for page in reader.pages]
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Could not extract PDF text.") from exc
    if any(part.strip() for part in parts):
        return "\n".join(parts)
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ValidationError("Scanned PDF requires pypdfium2, pytesseract, and Tesseract OCR.") from exc
    try:
        document = pdfium.PdfDocument(str(path))
        return "\n".join(_ocr_image(document[index].render(scale=1.5).to_pil()) for index in range(len(document)))
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Scanned PDF OCR failed.") from exc


def validate_file(path):
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValidationError("Supported file types: CSV, PDF, PNG, JPG, JPEG.")
    if not path.is_file():
        raise ValidationError("Input file does not exist.")
    if path.stat().st_size > MAX_SIZE:
        raise ValidationError("File exceeds the 15 MB local processing limit.")
    raw_bytes = path.read_bytes()
    if not raw_bytes:
        raise ValidationError("Input file is empty.")
    ext = path.suffix.lower()
    if ext == ".csv":
        records = parse_csv(path, raw_bytes)
        source = "csv"
    else:
        text = _read_pdf(path) if ext == ".pdf" else _read_image(path)
        records = parse_labeled_document_text(text, raw_bytes)
        source = "pdf" if ext == ".pdf" else "image"
    return {
        "schema_version": "1.0",
        "source_type": source,
        "source_file": path.name,
        "records": records,
        "summary": {
            "total": len(records),
            "ok": sum(item["status"] == "OK" for item in records),
            "review_required": sum(item["status"] == "REVIEW_REQUIRED" for item in records),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Local CSV, PDF or image file")
    parser.add_argument("--output", help="Optional destination JSON file")
    args = parser.parse_args(argv)
    try:
        result = validate_file(args.file)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
        else:
            sys.stdout.write(payload)
        return 0
    except (ValidationError, OSError) as exc:
        print(f"Validation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
