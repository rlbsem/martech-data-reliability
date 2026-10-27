"""Exercise actual read-only console, responsive states, raw lineage and independent receipts."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
AXE_SHA = "880970c081707360e64f34cea25ff91892f5bc95675b0776925b9709dd8a68bb"
VIEWS = ["overview", "sources", "candidates", "lineage", "recovery"]


def browser_check(url, output):
    assert urlparse(url).hostname in {"127.0.0.1", "localhost"} and urlparse(url).scheme == "http"
    output = Path(output)
    if output.exists():
        raise ValueError("fresh_browser_output_required")
    output.mkdir(parents=True)
    axe = ROOT / "operations_tests/vendor/axe.min.js"
    assert hashlib.sha256(axe.read_bytes()).hexdigest() == AXE_SHA
    checks, scans, errors, writes, external, screenshots = [], [], [], [], [], {}

    def require(name, passed):
        assert passed, name
        checks.append({"check": name, "passed": True})

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1200}, reduced_motion="reduce")
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: writes.append(r.method) if r.method != "GET" else None)
        page.on("request", lambda r: external.append(r.url) if not r.url.startswith(url) else None)
        page.add_init_script(script=axe.read_text(encoding="utf-8"))
        page.goto(url)
        page.locator("#status").filter(has_text="Actual local evidence loaded").wait_for()
        for width in [1440, 1024, 768, 390, 320]:
            page.set_viewport_size({"width": width, "height": 1100 if width > 768 else 844})
            for view in VIEWS:
                button = page.locator(f'[data-view="{view}"]')
                button.focus()
                page.keyboard.press("Enter")
                require(
                    f"{width}:{view}:keyboard_selection",
                    button.get_attribute("aria-pressed") == "true",
                )
                require(
                    f"{width}:{view}:no_page_overflow",
                    not page.evaluate("document.documentElement.scrollWidth>innerWidth"),
                )
                if width in [1440, 390]:
                    result = page.evaluate(
                        "async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length}}"
                    )
                    assert not result["violations"], "automated_accessibility_violation"
                    followups = []
                    for issue in result["incomplete"]:
                        for node in issue["nodes"]:
                            target = page.locator(node["target"][0])
                            assert target.count() == 1
                            target.evaluate("e=>e.scrollIntoView({block:'center',inline:'center'})")
                            detail = target.evaluate(
                                "async(e,rule)=>{const r=await axe.run(e,{runOnly:{type:'rule',values:[rule]}});return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length}}",
                                issue["id"],
                            )
                            followups.append(
                                {"rule": issue["id"], "target": node["target"], **detail}
                            )
                    scans.append(
                        {"width": width, "view": view, **result, "visibility_followups": followups}
                    )
        page.set_viewport_size({"width": 1440, "height": 1200})
        page.locator('[data-view="candidates"]').click()
        options = page.locator("#candidate option").evaluate_all(
            "es=>es.map(e=>({id:e.value,text:e.textContent}))"
        )
        for option in options:
            page.locator("#candidate").select_option(option["id"])
            require(
                "candidate_selection:" + option["text"],
                option["text"].split(" · ", 1)[1] in page.locator("#panel").inner_text(),
            )
        corrupted = next(o for o in options if "Equal row count, wrong values" in o["text"])
        page.locator("#candidate").select_option(corrupted["id"])
        page.get_by_text("Exact independent value differences", exact=True).click()
        require(
            "actual_value_difference_exposed",
            '"expected"' in page.locator("#panel details").first.inner_text()
            and '"actual"' in page.locator("#panel details").first.inner_text(),
        )
        page.locator('[data-view="sources"]').click()
        page.get_by_role("button", name="Read source receipt · website / 2", exact=True).click()
        page.locator("#readback").filter(has_text="ack_id").wait_for()
        require(
            "live_independent_receipt_does_not_advance_checkpoint",
            '"checkpoint_changed": false' in page.locator("#readback").inner_text(),
        )
        page.get_by_role("button", name="Inspect delivery · advertising / 4", exact=True).click()
        page.locator("#source-raw").filter(has_text="exact_base64").wait_for()
        require(
            "rejected_schema_raw_input_inspectable",
            "unsupported-schema" in page.locator("#source-raw").inner_text(),
        )
        page.locator('[data-view="lineage"]').click()
        page.get_by_role("button", name="Inspect raw · campaigns / partner", exact=True).click()
        page.locator("#raw-record").filter(has_text="exact_base64").wait_for()
        require(
            "exact_raw_delivery_inspectable", '"sha256"' in page.locator("#raw-record").inner_text()
        )
        require("raw_inspection_focus", page.evaluate("document.activeElement.id") == "raw-record")
        # UI failure rendering is separately labeled; real endpoint outages run in regressions.
        page.route(
            "**/api/state",
            lambda r: r.fulfill(status=503, json={"error": "controlled_browser_read_failure"}),
        )
        page.locator("#refresh").click()
        page.locator("#status").filter(has_text="Read-only evidence unavailable").wait_for()
        require(
            "failed_refresh_clears_prior_metrics", page.locator("#metrics .metric").count() == 0
        )
        require(
            "failure_does_not_imply_empty_or_complete",
            "No empty, complete or successful state is inferred"
            in page.locator("#panel").inner_text(),
        )
        page.unroute("**/api/state")
        page.locator("#refresh").click()
        page.locator("#status").filter(has_text="Actual local evidence loaded").wait_for()
        page.locator('[data-view="overview"]').click()
        page.evaluate("scrollTo(0,0)")
        page.screenshot(path=str(output / "operations-desktop.png"))
        screenshots["operations-desktop.png"] = {"width": 1440, "height": 1200, "view": "overview"}
        page.locator('[data-view="candidates"]').click()
        page.locator("#candidate").select_option(corrupted["id"])
        page.get_by_text("Exact independent value differences", exact=True).click()
        page.locator("#panel").scroll_into_view_if_needed()
        page.screenshot(path=str(output / "candidate-variance.png"))
        screenshots["candidate-variance.png"] = {
            "width": 1440,
            "height": 1200,
            "view": "candidates",
            "candidate": corrupted["text"],
        }
        page.set_viewport_size({"width": 390, "height": 1000})
        page.locator('[data-view="sources"]').click()
        page.locator("#panel").scroll_into_view_if_needed()
        page.screenshot(path=str(output / "operations-mobile.png"))
        screenshots["operations-mobile.png"] = {"width": 390, "height": 1000, "view": "sources"}
        require("browser_has_no_http_writes", not writes)
        require("browser_has_no_external_requests", not external)
        require("browser_has_no_runtime_errors", not errors)
        version = browser.version
        browser.close()
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "browser": "Chromium " + version,
        "scope": "Actual local HTTP sources and DuckDB-backed read-only console",
        "checks": checks,
        "responsive_states": 25,
        "accessibility": scans,
        "axe_sha256": AXE_SHA,
        "axe_version": "4.10.3",
        "images": screenshots,
        "image_sha256": {
            n: hashlib.sha256((output / n).read_bytes()).hexdigest() for n in screenshots
        },
        "source_sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "src/reliability_ops/web").iterdir())
        },
        "page_errors": errors,
        "http_writes": writes,
        "external_requests": external,
        "ui_failure_case": "Browser-intercepted 503, distinct from actual source-outage regression",
        "native_vendor_calls": 0,
    }
    (output / "browser.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    assert all(
        not r["violations"]
        and all(
            not f["violations"] and not f["incomplete"] and f["passes"]
            for f in r["visibility_followups"]
        )
        for r in scans
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "browser_assertions": len(checks),
                "accessibility_states": len(scans),
                "screenshots": len(screenshots),
            }
        )
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    browser_check(args.url, args.output)
