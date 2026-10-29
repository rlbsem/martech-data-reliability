"""Check actual delivery evidence, preserved history and exact public package inventory."""

import argparse
import hashlib
import json
import re
import subprocess

from verify_operations import ROOT, sources


def public_files():
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in sorted(set(names))
        if name != "docs/evidence/delivery/package-manifest.json"
    }


def check():
    out = ROOT / "docs/evidence/delivery/run01"
    hashes = json.loads((out / "artifact-integrity.json").read_bytes())
    assert {p.name for p in out.iterdir() if p.is_file()} == {*hashes, "artifact-integrity.json"}
    for name, sha in hashes.items():
        assert (out / name).resolve().is_relative_to(out.resolve())
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == sha
    report = json.loads((out / "verification.json").read_bytes())
    assert report["status"] == "passed" and report["source_sha256"] == sources()
    assert all(c["passed"] and c["expected"] == c["observed"] for c in report["checks"])
    required = {
        "verified_readiness",
        "remote_ahead_restore_held",
        "backup_verified",
        "restore_verified",
        "corrupt_retained_input_not_ready",
        "owned_processes_stopped",
    }
    assert required <= {c["check"] for c in report["checks"]}
    assert len(report["screenshots"]) == 6 and len(report["accessibility"]) == 6
    assert all(not scan["violations"] for scan in report["accessibility"])
    assert all(
        not f["violations"] and not f["incomplete"] and f["passes"]
        for scan in report["accessibility"]
        for f in scan["visibility_followups"]
    )
    for name, sha in report["screenshots"].items():
        assert hashes[name] == sha
    for p in out.glob("*.json"):
        assert not re.search(r'"(?:read_token|ack_token|password|api_secret)"\s*:', p.read_text())
    old = json.loads((ROOT / "docs/evidence/delivery/preserved-files.json").read_bytes())
    for name, sha in old.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
    manifest = json.loads((ROOT / "docs/evidence/delivery/package-manifest.json").read_bytes())
    assert manifest == public_files(), "public_package_inventory_changed"
    print(
        json.dumps(
            {
                "status": "passed",
                "delivery_checks": len(report["checks"]),
                "historical_files_preserved": len(old),
                "package_files": len(manifest),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-package-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_package_manifest:
        path = ROOT / "docs/evidence/delivery/package-manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(public_files(), indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        check()
