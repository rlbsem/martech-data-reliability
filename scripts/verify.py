"""One command executes tests, crashes, deterministic demo and source-bound evidence."""

import importlib.metadata
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import marketing_reliability

from crash_proof import execute as crash_proof
from demo import execute as demo
from marketing_reliability.contracts import digest, implementation_hash
from repository import ROOT, fingerprint, inventory, links, save, source_manifest


def run(*args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main():
    before = fingerprint()
    work = ROOT / "work/verification" / uuid4().hex
    work.mkdir(parents=True)
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    installed = Path(marketing_reliability.__file__).parent
    source = ROOT / "src/marketing_reliability"
    for requirement in (ROOT / "requirements.lock").read_text().splitlines():
        package, version = requirement.split("==")
        assert importlib.metadata.version(package) == version, f"lock mismatch: {package}"
    for file in source.rglob("*"):
        if file.suffix in (".py", ".sql"):
            assert file.read_bytes() == (installed / file.relative_to(source)).read_bytes(), (
                "installed package differs from source"
            )
    run("-m", "pip", "check")
    run("-m", "ruff", "check", ".")
    run("-m", "ruff", "format", "--check", ".")
    run(
        "-m",
        "pytest",
        "-q",
        "-o",
        f"cache_dir={work / 'cache'}",
        f"--basetemp={work / 'tests'}",
        f"--junitxml={evidence / 'tests.xml'}",
    )
    suites = ET.parse(evidence / "tests.xml").getroot()
    totals = {
        name: sum(int(s.get(name, 0)) for s in suites.iter("testsuite"))
        for name in ("tests", "failures", "errors", "skipped")
    }
    assert totals["tests"] > 0 and not any(totals[k] for k in ("failures", "errors", "skipped"))
    demo(work / "demo-a", evidence)
    demo(work / "demo-b", work / "repeat")
    for name in ("reconciliation.json", "lineage.json", "pipeline-runs.json", "report.md"):
        assert (evidence / name).read_bytes() == (work / "repeat" / name).read_bytes(), name
    crashes = crash_proof(work / "crashes", evidence / "recovery.json")
    run(
        "-m",
        "pip",
        "wheel",
        "--no-cache-dir",
        "--no-index",
        "--no-deps",
        "--no-build-isolation",
        "--wheel-dir",
        str(work / "wheels"),
        ".",
    )
    wheel = next(work.joinpath("wheels").glob("*.whl"))
    with ZipFile(wheel) as archive:
        packaged = 0
        for file in source.rglob("*"):
            if file.suffix in (".py", ".sql"):
                assert (
                    archive.read("marketing_reliability/" + file.relative_to(source).as_posix())
                    == file.read_bytes()
                )
                packaged += 1
    assert fingerprint() == before, "source changed during verification"
    link_count = 0
    save(
        evidence / "verification.json",
        {
            "verified_at_utc": datetime.now(UTC).isoformat(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "duckdb": importlib.metadata.version("duckdb"),
            "tests": totals,
            "crash_experiments": len(crashes),
            "demo_byte_reproducible": True,
            "installed_package_matches_source": True,
            "installation": "source/editable"
            if installed.resolve() == source.resolve()
            else "installed wheel",
            "wheel_source_and_sql_members_checked": packaged,
            "internal_markdown_links_checked": link_count,
            "dependency_check": "passed",
            "lint": "passed",
            "format": "passed",
            "implementation_sha256": implementation_hash(),
            "source_fingerprint": before,
            "source_files": source_manifest(),
            "github_hosted_ci": "not executed",
            "cloud_or_vendor_integration": "not executed",
            "generated_evidence": {
                p.name: digest(p.read_bytes())
                for p in evidence.iterdir()
                if p.name
                in (
                    "tests.xml",
                    "recovery.json",
                    "pipeline-runs.json",
                    "reconciliation.json",
                    "lineage.json",
                    "report.md",
                )
            },
        },
    )
    link_count = links()
    record = json.loads((evidence / "verification.json").read_text())
    record["internal_markdown_links_checked"] = link_count
    save(evidence / "verification.json", record)
    inventory()
    print(
        f"VERIFIED: {totals['tests']} tests; {len(crashes)} process-death experiments; deterministic demo; wheel parity; {link_count} local links"
    )


if __name__ == "__main__":
    main()
