"""Fresh, source-bound native HTTP/DuckDB/browser acceptance; never rewrites historical evidence."""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

import duckdb

from browser_operations import browser_check
from crash_proof import execute as original_crashes
from demo import execute as original_demo
from reliability_ops.common import save
from reliability_ops.demo import execute
from reliability_ops.runtime import LocalRuntime, free_port
from reliability_ops.view import verify_live

ROOT = Path(__file__).resolve().parents[1]


def sources():
    paths = [
        p
        for folder in ["src", "scripts", "tests", "operations_tests", "fixtures", ".github"]
        for p in (ROOT / folder).rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix in {".py", ".sql", ".html", ".js", ".css", ".json", ".yml"}
    ]
    paths += [
        ROOT / n
        for n in [
            "requirements.lock",
            "requirements-operations.lock",
            "pyproject.toml",
            "Dockerfile",
            "compose.yaml",
            ".gitattributes",
            ".dockerignore",
        ]
    ]
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


def command(args, log):
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            [sys.executable, *args], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=900
        )
    if result.returncode:
        raise RuntimeError("verification failed; inspect private workspace " + log.name)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    work, out = a.workspace.resolve(), a.output.resolve()
    if work.exists() or out.exists():
        raise ValueError("fresh_workspace_and_output_required")
    work.mkdir(parents=True)
    out.mkdir(parents=True)
    before = sources()
    started = datetime.now(UTC).isoformat()
    revision = None
    if shutil.which("git"):
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            revision = r.stdout.strip()
    command(["-m", "ruff", "check", "."], work / "lint.log")
    command(["-m", "ruff", "format", "--check", "."], work / "format.log")
    command(["-m", "pip", "check"], work / "dependencies.log")
    suites = {}
    for suite, folder in [("original", "tests"), ("operations", "operations_tests")]:
        xml = work / (suite + ".xml")
        command(
            [
                "-m",
                "pytest",
                folder,
                "-q",
                "--basetemp",
                str(work / (suite + "-tests")),
                "--junitxml",
                str(xml),
            ],
            work / (suite + ".log"),
        )
        root = ET.parse(xml).getroot()
        totals = {
            k: sum(int(n.attrib[k]) for n in root.iter("testsuite"))
            for k in ["tests", "errors", "failures", "skipped"]
        }
        assert not any(totals[k] for k in ["errors", "failures", "skipped"])
        totals["cases"] = [
            n.attrib["classname"] + "." + n.attrib["name"] for n in root.iter("testcase")
        ]
        suites[suite] = totals
    original_demo(work / "original-demo-a", out / "original-demo")
    original_demo(work / "original-demo-b", work / "original-repeat")
    for name in ["reconciliation.json", "lineage.json", "pipeline-runs.json", "report.md"]:
        assert (out / "original-demo" / name).read_bytes() == (
            work / "original-repeat" / name
        ).read_bytes()
    crashes = original_crashes(work / "original-crashes", out / "original-recovery.json")
    # Preserve the original report's relative recovery link in its fresh subdirectory.
    shutil.copyfile(out / "original-recovery.json", out / "original-demo/recovery.json")
    command(
        [
            "-m",
            "pip",
            "wheel",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(work / "wheels"),
            ".",
        ],
        work / "wheel.log",
    )
    wheel = next((work / "wheels").glob("*.whl"))
    with ZipFile(wheel) as archive:
        members = {
            p.relative_to(ROOT / "src").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "src").rglob("*")
            if p.is_file() and p.suffix in {".py", ".sql", ".html", ".css", ".js"}
        }
        assert all(hashlib.sha256(archive.read(n)).hexdigest() == h for n, h in members.items())
    save(
        out / "wheel-verification.json",
        {
            "status": "passed",
            "members_sha256": members,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "scope": "Actual built-wheel code, SQL and UI member byte comparison",
        },
    )
    with LocalRuntime(work / "native") as runtime:
        report = execute(runtime.config, runtime.source_configs, runtime.root / "controller.json")
        readonly = json.loads((runtime.root / "console.json").read_bytes())
        independent = verify_live(readonly)
        port = free_port()
        runtime.spawn("console", runtime.root / "console.json", port)
        url = f"http://127.0.0.1:{port}/"
        for _ in range(50):
            try:
                urlopen(url + "health", timeout=2).close()
                break
            except OSError:
                time.sleep(0.1)
        browser = browser_check(url, out / "browser")
    original = json.loads((ROOT / "docs/evidence/operations/original-files.json").read_bytes())
    assert all(
        hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h
        for n, h in original["sha256"].items()
    )
    assert before == sources(), "source_changed_during_execution"
    result = {
        "status": "passed",
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "git_revision": revision,
        "source_sha256": before,
        "python": platform.python_version(),
        "platform": platform.system(),
        "duckdb": duckdb.__version__,
        "suites": suites,
        "original_crash_experiments": len(crashes),
        "original_demo_byte_parity": True,
        "native_scenario_assertions": len(report["checks"]),
        "independent_read_only_validation": independent,
        "browser_assertions": len(browser["checks"]),
        "automated_accessibility_states": len(browser["accessibility"]),
        "owned_processes_stopped": all(c.poll() is not None for c, _ in runtime.children),
        "original_files_preserved": len(original["sha256"]),
        "synthetic": True,
        "native_marketing_vendor_calls": 0,
        "docker": {
            "executed_by_this_command": False,
            "local_cli_available": shutil.which("docker") is not None,
            "scope": "Separate Linux CI lane",
        },
    }
    save(out / "acceptance.json", report)
    save(out / "verification.json", result)
    artifacts = {
        p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.rglob("*"))
        if p.is_file()
    }
    save(out / "artifact-integrity.json", artifacts)
    print(
        json.dumps(
            {
                "status": "passed",
                "original_tests": suites["original"]["tests"],
                "operations_tests": suites["operations"]["tests"],
                "scenario_assertions": len(report["checks"]),
                "original_crashes": len(crashes),
                "browser_assertions": len(browser["checks"]),
            }
        )
    )


if __name__ == "__main__":
    main()
