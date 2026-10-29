"""Actual isolated service, backup, restore, failure and browser acceptance. No cloud."""

import argparse
import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

from browser_operations import AXE_SHA
from reliability_ops.backup import backup, restore
from reliability_ops.common import now, save, sqlite
from reliability_ops.demo import execute
from reliability_ops.runtime import LocalRuntime, free_port
from verify_operations import ROOT, sources


def get(url):
    try:
        with urlopen(url, timeout=30) as r:
            return r.status, json.load(r)
    except HTTPError as r:
        return r.code, json.load(r)


def run(work, out):
    if work.exists() or out.exists():
        raise ValueError("fresh_workspace_and_evidence_required")
    out.mkdir(parents=True)
    before, checks, screens, observations = sources(), [], {}, []

    def require(name, actual, expected):
        save(
            out / "progress.json",
            {"checks": checks, "current_check": name, "actual": actual, "expected": expected},
        )
        assert actual == expected, name
        checks.append({"check": name, "observed": actual, "expected": expected, "passed": True})

    with LocalRuntime(work) as runtime:
        execute(runtime.config, runtime.source_configs, runtime.root / "controller.json")
        conf = json.loads((runtime.root / "console.json").read_bytes())
        port = free_port()
        process = runtime.spawn("console", runtime.root / "console.json", port)
        url = f"http://127.0.0.1:{port}/"
        for _ in range(100):
            try:
                if get(url + "livez")[0] == 200:
                    break
            except OSError:
                time.sleep(0.1)
        ready = get(url + "readyz")
        require("verified_readiness", [ready[0], ready[1]["status"]], [200, "ready"])
        require(
            "independent_source_economics",
            ready[1]["totals"],
            {
                "cost_cents": 41000,
                "impressions": 4000,
                "clicks": 400,
                "conversions": 6,
                "revenue_cents": 115000,
            },
        )
        for method in ["POST", "PATCH", "PUT", "DELETE"]:
            try:
                urlopen(Request(url + "api/operations", data=b"{}", method=method))
                raise AssertionError("public_mutation_accepted")
            except HTTPError as error:
                require("read_only_" + method, error.code, 405)
        archive = runtime.root / "private-backup"
        require("backup_verified", backup(conf, archive)["status"], "passed")
        require(
            "restore_verified",
            restore(conf, archive, runtime.root / "restored")["status"],
            "passed",
        )
        axe = ROOT / "operations_tests/vendor/axe.min.js"
        assert hashlib.sha256(axe.read_bytes()).hexdigest() == AXE_SHA
        errors, writes, external = [], [], []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(reduced_motion="reduce")
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: writes.append(r.method) if r.method != "GET" else None)
            page.on(
                "request", lambda r: external.append(r.url) if not r.url.startswith(url) else None
            )
            page.add_init_script(axe.read_text(encoding="utf-8"))
            for condition in ["ready", "source-outage"]:
                if condition == "source-outage":
                    with sqlite(runtime.source_configs["website"]["db"]) as c:
                        c.execute("UPDATE faults SET mode='outage'")
                    require("outage_not_ready", get(url + "readyz")[0], 503)
                    require("outage_still_alive", get(url + "livez")[0], 200)
                    require(
                        "last_publication_retained",
                        get(url + "api/state")[1]["warehouse"]["active_run"],
                        ready[1]["active_run"],
                    )
                for width in [1440, 390, 320]:
                    page.set_viewport_size(
                        {"width": width, "height": 1100 if width == 1440 else 844}
                    )
                    page.goto(url)
                    page.locator("#candidate option").first.wait_for(state="attached")
                    button = page.locator('[data-view="operations"]')
                    button.focus()
                    page.keyboard.press("Enter")
                    page.locator("#readiness-status").filter(
                        has_text=("Ready ·" if condition == "ready" else "Not ready ·")
                    ).wait_for()
                    require(
                        f"{condition}:{width}:no_overflow",
                        page.evaluate("document.documentElement.scrollWidth<=innerWidth"),
                        True,
                    )
                    result = page.evaluate(
                        "async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}); return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length}}"
                    )
                    require(f"{condition}:{width}:accessibility", result["violations"], [])
                    # New view has no scrollable tables; unresolved audits are retained, never called passes.
                    observations.append({"condition": condition, "width": width, **result})
                    name = f"operations-{condition}-{width}.png"
                    page.screenshot(path=str(out / name), full_page=True)
                    screens[name] = hashlib.sha256((out / name).read_bytes()).hexdigest()
            browser.close()
        require("browser_errors", errors, [])
        require("browser_mutations", writes, [])
        require("browser_external_requests", external, [])
        with sqlite(runtime.source_configs["website"]["db"]) as c:
            c.execute("UPDATE faults SET mode='none'")
        require("dependency_recovers", get(url + "readyz")[0], 200)
        process.terminate()
        process.wait(timeout=10)
        runtime.spawn("console", runtime.root / "console.json", port)
        for _ in range(100):
            try:
                if get(url + "livez")[0] == 200:
                    break
            except OSError:
                time.sleep(0.1)
        require(
            "console_restart_preserves_publication",
            get(url + "readyz")[1]["active_run"],
            ready[1]["active_run"],
        )
        raw = next((Path(conf["state"]) / "warehouse/landing").glob("*.json"))
        old = raw.read_bytes()
        raw.write_bytes(b"{}")
        require("corrupt_retained_input_not_ready", get(url + "readyz")[0], 503)
        raw.write_bytes(old)
        require("restored_original_bytes_ready", get(url + "readyz")[0], 200)
        from reliability_ops.source import claim

        claim(runtime.source_configs["website"], "web", 99, complete=False, through="2026-09-05")
        require("new_incomplete_coverage_not_ready", get(url + "readyz")[0], 503)
        try:
            restore(conf, archive, runtime.root / "held-restore")
            raise AssertionError("stale_restore_admitted")
        except ValueError as error:
            require(
                "remote_ahead_restore_held",
                str(error),
                "restore_not_ready_against_independent_sources",
            )
        log_rows = []
    for _, stream in runtime.children:
        for line in Path(stream.name).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            assert set(row) <= {
                "at",
                "event",
                "service",
                "request_id",
                "route",
                "status",
                "duration_ms",
            }
            log_rows.append(row)
    require("owned_processes_stopped", all(c.poll() is not None for c, _ in runtime.children), True)
    require("source_unchanged_during_acceptance", sources(), before)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    report = {
        "status": "passed",
        "executed_at": now(),
        "git_revision": revision,
        "source_sha256": before,
        "platform": platform.system(),
        "python": platform.python_version(),
        "checks": checks,
        "readiness": ready[1],
        "screenshots": screens,
        "accessibility": observations,
        "structured_log_rows": len(log_rows),
        "synthetic": True,
        "native_vendor_calls": 0,
        "cloud_resources": 0,
        "acceptance_boundary": "local_subprocess_http_and_browser",
        "independent_human_acceptance": "not_executed",
        "public_hosted_acceptance": "not_executed",
    }
    save(out / "verification.json", report)
    save(out / "request-telemetry.json", log_rows)
    (out / "progress.json").unlink()
    save(
        out / "artifact-integrity.json",
        {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.iterdir())
            if p.is_file()
        },
    )
    print(json.dumps({"status": "passed", "checks": len(checks), "screenshots": len(screens)}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    run(args.workspace.resolve(), args.output.resolve())
