"""Validate current execution bytes, source accounting, preserved failures and screenshot integrity."""

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

from marketing_reliability.contracts import canonical, digest

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check(folder):
    folder = folder.resolve()
    inventory = json.loads((folder / "artifact-integrity.json").read_bytes())
    assert {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()} == {
        *inventory,
        "artifact-integrity.json",
    }
    for n, h in inventory.items():
        p = (folder / n).resolve()
        assert p.is_relative_to(folder) and sha(p) == h, "recorded_artifact_changed"
    v = json.loads((folder / "verification.json").read_bytes())
    assert (
        v["status"] == "passed"
        and v["owned_processes_stopped"]
        and v["native_marketing_vendor_calls"] == 0
    )
    assert all(sha(ROOT / n) == h for n, h in v["source_sha256"].items()), "executed_source_changed"
    original = json.loads((ROOT / "docs/evidence/operations/original-files.json").read_bytes())
    assert all(sha(ROOT / n) == h for n, h in original["sha256"].items()), "original_bytes_changed"
    assert v["suites"]["original"]["tests"] == 68 and v["original_crash_experiments"] == 8
    for suite in v["suites"].values():
        assert len(suite["cases"]) == suite["tests"] and all(
            suite[k] == 0 for k in ["errors", "failures", "skipped"]
        )
    report = json.loads((folder / "acceptance.json").read_bytes())
    assert len(report["checks"]) == 30 and all(
        c["passed"] and c["expected"] == c["observed"] for c in report["checks"]
    )
    assert report["synthetic"] and report["native_marketing_vendor_calls"] == 0
    candidates = report["snapshot"]["candidates"]
    for delivery in report["snapshot"]["retained_remote_deliveries"]:
        assert (
            digest(base64.b64decode(delivery["exact_base64"], validate=True)) == delivery["sha256"]
        )
    wrong = next(c for c in candidates if c["name"] == "Equal row count, wrong values")
    assert len(wrong["raw_oracle"]["differences"]) == 1, "rejected_value_evidence_missing"
    active = next(
        c for c in candidates if c["run"]["id"] == report["snapshot"]["warehouse"]["active_run"]
    )
    assert active["raw_oracle"]["differences"] == active["raw_oracle"]["unresolved"] == []
    for candidate in candidates:
        oracle = candidate["raw_oracle"]
        assert oracle["accepted_rows"] == sum(oracle["row_dispositions"].values())
        assert oracle["unique_versions"] == oracle["row_dispositions"]["admitted"]
        assert oracle["latest_records"] + oracle["superseded"] == oracle["unique_versions"]
        assert digest(canonical(candidate["table"]).encode()) == oracle["table_sha256"]
    for source in report["independent_source_receipts"].values():
        for row in source["acknowledgments"]:
            body = json.loads(row["body"])
            assert body["ack_id"] == digest(
                canonical({k: v for k, v in body.items() if k != "ack_id"}).encode()
            )
    browser = json.loads((folder / "browser/browser.json").read_bytes())
    assert len(browser["checks"]) == 73 and all(c["passed"] for c in browser["checks"])
    assert len(browser["accessibility"]) == 10 and browser["responsive_states"] == 25
    for scan in browser["accessibility"]:
        assert not scan["violations"]
        assert sum(len(i["nodes"]) for i in scan["incomplete"]) == len(scan["visibility_followups"])
        assert all(
            not f["violations"] and not f["incomplete"] and f["passes"]
            for f in scan["visibility_followups"]
        )
    assert not any(browser[k] for k in ["page_errors", "http_writes", "external_requests"])
    assert all(sha(folder / "browser" / n) == h for n, h in browser["image_sha256"].items())
    for p in folder.rglob("*.json"):
        body = p.read_text(encoding="utf-8")
        assert not re.search(r'"(?:read_token|ack_token|password|api_secret)"\s*:', body), (
            "private_credential_field"
        )
    print(
        json.dumps(
            {
                "status": "passed",
                "immutable_artifacts": len(inventory),
                "preserved_original_files": len(original["sha256"]),
                "independent_receipts": v["independent_read_only_validation"][
                    "independent_source_receipts"
                ],
                "source_rows": active["raw_oracle"]["accepted_rows"],
                "candidate_rows": len(active["table"]),
                "value_differences": 0,
                "browser_assertions": 73,
            }
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--evidence", type=Path, default=ROOT / "docs/evidence/operations/run02")
    args = p.parse_args()
    check(args.evidence)
