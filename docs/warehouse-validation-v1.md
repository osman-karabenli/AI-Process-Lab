# Warehouse input foundation (development version)

This is a **separate first increment**, not a replacement for the original n8n/Ollama/PostgreSQL workflow. The existing workflow is unchanged, and automatic n8n hand-off is not implemented yet. There is no live ERP or SAP connection.

## What is supported

- **CSV**: UTF-8 files with required headers 'supplier,material,quantity'. German aliases 'Lieferant,Artikel,Menge' are also accepted, as are semicolon or tab delimiters. Each non-empty row is checked, and quantity must be a positive whole number. Results are 'OK' or 'REVIEW_REQUIRED'.
- **Text PDFs**: text is extracted using optional 'pypdf'. For scanned PDFs, optional 'pypdfium2' rendering and Tesseract local OCR are used.
- **PNG/JPG images**: local OCR via Pillow, pytesseract and system Tesseract, with English and German language packs.
- **Document extraction has a deliberately narrow scope**: one labeled record per document, for example 'Supplier:', 'Material:', 'Quantity:' or 'Lieferant:', 'Artikel:', 'Menge:'. Complex/unlabeled layouts may return missing fields.
- **Every PDF and image record remains 'REVIEW_REQUIRED' even if all fields were recognized**. A person must verify the information before posting to other systems.
- Processing is **local**: this tool makes no remote calls.

## Quick start

Requires Python 3.10 or later:

    python -m warehouse_validator.validator sample.csv --output report.json
    python -m unittest discover -s tests -v

For PDFs and images install optional dependencies:

    python -m pip install '.[documents]'

For images and scanned PDFs additionally install system **Tesseract OCR** with both English ('eng') and German ('deu') language packs.

Example 'sample.csv':

    supplier,material,quantity
    Bosch,Motor A12,100
    Siemens,Sensor B25,
    ABB,Kabel C30,50

Expected summary: 2 'OK', 1 'REVIEW_REQUIRED' with missing field 'quantity'.

## JSON contract

Output contains 'schema_version', 'source_type', 'source_file', 'records' and 'summary'. Each record includes a content-derived 'record_id', normalized fields, 'status', 'missing_fields', 'errors' and 'review_reasons'.

The record IDs are derived from source file bytes and row numbers. They are **not ERP business identifiers**. Reprocessing identical file bytes produces identical IDs, but the tool does not implement database deduplication. The existing n8n workflow still generates independent IDs.

Limits: max 15 MB file and 10 PDF pages. CSV quantities must be positive integers without separators or decimal values. No custom column mapping, multi-document extraction, purchase-order matching, UI, cloud hosting, automatic file monitoring, ERP posting, end-to-end n8n integration, or automatic document approval.

## Long-term architecture

    CSV / PDF / image
          |
    local extraction and normalization        [first increment implemented]
          |
    validation + human-review requirement      [basic status implemented]
          |
    existing n8n + optional Ollama             [future adapter; original POC preserved]
          |
    existing PostgreSQL audit log              [not connected to this tool yet]
          |
    ERP / SAP                                  [interface planned; not connected]

An ERP adapter should start read-only, use an authorized test system and customer-owned credentials, and require manual authorization before writebacks. Do not upload sensitive documents, live credentials or real order data to the public GitHub repository or the marketplace.

## Agensi product strategy (not published)

Two focused Skills can later share this foundation:

1. **Delivery Note Validator** — extract and flag incoming delivery-note information for human review.
2. **Purchase Order Matching** — compare reviewed delivery-note values with authorized order records, once read-only ERP/API access exists.

Before publishing, prepare separate standalone ZIP packages, each with 'SKILL.md' at the root, scripts, clear local prerequisites, tests and security review. Current repository does **not** include a published/validated Agensi Skill.

## Testing limits

Unit tests cover CSV normalization, status decisions, stable IDs and limited document-text parsing. PDF and image dispatch tests use mocks, so they do **not** prove that real-world OCR succeeds. The GitHub Actions workflow runs these unit tests for commits and pull requests.
