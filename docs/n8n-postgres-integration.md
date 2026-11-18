# Step 2 — CSV/PDF/image validation → n8n → PostgreSQL (local pilot)

**Status:** Implemented as a separate n8n workflow plus a Python sender. The existing `01 - AI Document Analyzer.json` remains unchanged. This is not connected to a production ERP, and **no live n8n/PostgreSQL run has been verified**.

## Architecture

```text
Local CSV/PDF/image file
       |
warehouse_validator.validator (local parser + initial checks)
       |
warehouse_validator.n8n_client (POST one record at a time; explicit --send)
       |
n8n 02 - Warehouse Intake Webhook (Header Auth)
       |
Revalidate Record (deterministic checks, no LLM dependence)
       |
PostgreSQL ai_process_log (parameterized insert, ON CONFLICT DO NOTHING)
       |
JSON acknowledgment with record_id, status, inserted
```

The original n8n workflow with Ollama remains available as a separate demonstration. This new workflow deliberately does **not** ask the LLM to decide whether known structured fields are complete. That decision is deterministic. A future document-extraction subflow may use Ollama before these same checks.

## Preparation (local-only)

1. Use a **separate development branch** and follow the original README to start Docker Compose, PostgreSQL and n8n. Apply both SQL migrations in order: `V1__create_ai_process_log.sql` then `V2__add_unique_record_id.sql`.
2. Open n8n at `http://localhost:5678`; import `workflows/02 - Warehouse Intake Webhook.json`.
3. The imported **Warehouse Intake Webhook** uses **Header Auth**. Create a new Header Auth credential in n8n using name `X-Warehouse-Token` and a long randomly generated value (minimum 20 characters), and attach it to the Webhook node.
4. Select **Write Audit to PostgreSQL** and attach your existing locally configured PostgreSQL credential. Use Docker hostname `postgres`, port `5432`, and the database and credentials from your local `.env`. Never commit secrets.
5. Confirm that `Revalidate Record` uses the supplied code and that PostgreSQL is configured with the SQL query parameters. If the editor flags any imported setting or node version, review the node in your installed n8n version before running.
6. In n8n click **Listen for test event** on the Webhook node. While listening, the test URL is `http://127.0.0.1:5678/webhook-test/warehouse-receiving-v1`. For permanent use, activate the workflow and use `/webhook/warehouse-receiving-v1`; keep access strictly local, or use HTTPS with a suitable additional access policy before exposing it remotely.

## Windows PowerShell smoke test

From the repository root:

```powershell
# Dry-run, no network request:
python -m warehouse_validator.n8n_client examples/warehouse_receiving_demo.csv

# Enter your n8n Header Auth secret locally and run the test:
$env:WAREHOUSE_WEBHOOK_TOKEN = Read-Host "Paste your n8n webhook token"
python -m warehouse_validator.n8n_client examples/warehouse_receiving_demo.csv --send --url "http://127.0.0.1:5678/webhook-test/warehouse-receiving-v1"

# Clear the temporary secret in this shell:
Remove-Item Env:WAREHOUSE_WEBHOOK_TOKEN
```

Each record is sent separately, so the n8n test listener should remain available while the requests arrive. If your n8n test listener accepts only one incoming request, activate the workflow in a private local environment and use the production-style `/webhook/` URL instead.

Expected for the synthetic fixture: **8 records**, with **4 OK** and **4 REVIEW_REQUIRED**. Each successful response includes `record_id`, `status`, `missing_fields`, and `inserted`. Repeating the same file should result in `inserted: false` on existing record IDs due to the database uniqueness constraint.

## Verify PostgreSQL

In a locally authorized SQL console:

```sql
SELECT record_id, supplier, material, quantity, status, missing_fields,
       process_step, created_at
FROM ai_process_log
ORDER BY created_at DESC
LIMIT 20;
```

Never send real customer or patient data for this pilot. Use only synthetic warehouse examples. This flow makes local database writes; do not enable it for untrusted public access.

## Caveats

- Unit tests use a fake HTTP client and **cannot prove real n8n/PostgreSQL connectivity**. The live end-to-end check must be performed on your machine.
- Any PDF or image extracted record remains `REVIEW_REQUIRED` even when all fields were recognized, until a person verifies it.
- Both clients require the same `X-Warehouse-Token`; do not add it to GitHub or share screenshots showing its value.
- Records are deduplicated by a content-derived record ID (file bytes plus row). A changed file creates a new ID; **this is not business-level purchase-order deduplication**. ERP integration and record matching remain future work.
- The n8n webhook uses a fixed local path. Do not reuse credentials from another application.
- If the client receives a timeout, some records may already have been inserted. Retrying the same file is intended to be safe under `ON CONFLICT DO NOTHING`.
- Do not expose the n8n editor or webhook directly to the Internet without HTTPS and network restrictions.

## Local automated tests

```powershell
python -m unittest discover -s tests -v
```

The GitHub Actions workflow runs the same unit tests; it does **not** have your private n8n instance or Postgres database. Review the Actions status before merging.
