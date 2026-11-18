"""Send validated warehouse records to a local authenticated n8n webhook.

No network call is performed unless --send is provided.
"""
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from warehouse_validator.validator import ValidationError, validate_file


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValidationError("Unexpected webhook redirect; refusing to forward credentials.")


def validate_webhook_url(url):
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValidationError("Do not include credentials, queries, or fragments in webhook URL.")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValidationError("Webhook URL must start with http:// or https://.")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValidationError("Plain HTTP is only allowed for localhost. Use HTTPS for remote n8n.")
    if not (
        parsed.path.endswith("/webhook/warehouse-receiving-v1")
        or parsed.path.endswith("/webhook-test/warehouse-receiving-v1")
    ):
        raise ValidationError("URL must point to the warehouse-receiving-v1 webhook path.")
    return url


def send_report(report, webhook_url, token, *, opener=None):
    validate_webhook_url(webhook_url)
    if not token or len(token.strip()) < 20:
        raise ValidationError("Configure a strong X-Warehouse-Token (20+ characters).")
    opener = opener or build_opener(_NoRedirect)
    results = []
    for record in report["records"]:
        payload = {
            "schema_version": "1.0",
            "source_type": report["source_type"],
            "record": record,
        }
        req = Request(
            webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Warehouse-Token": token.strip(),
            },
            method="POST",
        )
        try:
            with opener.open(req, timeout=20) as resp:
                response = json.loads(resp.read().decode("utf-8"))
                if resp.status < 200 or resp.status >= 300:
                    raise ValidationError(f"n8n returned HTTP {resp.status}.")
        except (URLError, HTTPError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                f"Webhook failed for record {record['record_id']}: {type(exc).__name__}. "
                "Check n8n execution logs."
            ) from exc
        if (
            not isinstance(response, dict)
            or response.get("record_id") != record["record_id"]
            or response.get("status") not in ("OK", "REVIEW_REQUIRED")
            or not isinstance(response.get("inserted"), bool)
        ):
            raise ValidationError(
                f"Unexpected n8n acknowledgment for {record['record_id']}."
            )
        results.append(
            {
                "record_id": response["record_id"],
                "status": response["status"],
                "inserted": response["inserted"],
            }
        )
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Local CSV, PDF, JPG or PNG file")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:5678/webhook-test/warehouse-receiving-v1",
        help="n8n webhook URL (default: localhost test URL)",
    )
    parser.add_argument(
        "--send", action="store_true", help="Actually post to n8n; otherwise dry-run."
    )
    args = parser.parse_args(argv)
    try:
        report = validate_file(args.file)
        if not args.send:
            print(json.dumps(
                {"dry_run": True, "summary": report["summary"]},
                ensure_ascii=False, indent=2
            ))
            return 0
        token = os.environ.get("WAREHOUSE_WEBHOOK_TOKEN", "")
        result = send_report(report, args.url, token)
        print(json.dumps(
            {
                "records_sent": len(result),
                "inserted": sum(item["inserted"] for item in result),
                "duplicates": sum(not item["inserted"] for item in result),
                "results": result,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    except (ValidationError, OSError) as exc:
        print("Error:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
