"""Kill real CLI subprocesses at persistence boundaries and reopen their databases."""

import json
import subprocess
import sys
from pathlib import Path

from marketing_reliability.warehouse import Warehouse
from marketing_reliability.contracts import canonical

ROOT = Path(__file__).resolve().parents[1]
POINTS = (
    "after_landing",
    "during_ingest",
    "before_ingest_commit",
    "after_ingest_commit",
    "during_build",
    "after_build_commit",
    "before_publish_commit",
    "after_publish_commit",
)


def experiment(directory, point):
    state = directory / point
    with Warehouse(state) as w:
        for number in range(1, 5):
            w.ingest(next(ROOT.joinpath("fixtures").glob(f"{number:02d}-*.json")).read_bytes())
        baseline = w.plan("2026-09-04")
        w.build(baseline)
        w.publish(baseline)
        before = w.reconcile()
        if point in POINTS[:4]:
            operation = ["ingest", str(ROOT / "fixtures/05-web-corrections.json")]
        else:
            w.ingest(
                canonical(
                    {
                        "source": "web",
                        "batch_id": "crash-correction",
                        "schema_version": 1,
                        "covered_through": "2026-09-03",
                        "rows": [
                            {
                                "id": "w1",
                                "revision": 2,
                                "op": "upsert",
                                "day": "2026-09-01",
                                "campaign_id": "search",
                                "conversions": 0,
                            }
                        ],
                    }
                ).encode()
            )
            run = w.plan("2026-09-04", dates=["2026-09-01"])
            if "publish" in point:
                w.build(run)
                operation = ["publish", str(run)]
            else:
                operation = ["build", str(run)]
    command = [
        sys.executable,
        "-m",
        "marketing_reliability.cli",
        "--state",
        str(state),
        *operation,
        "--crash",
        point,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 86, result.stderr
    with Warehouse(state) as w:
        crashed = w.reconcile()
        if point == "after_publish_commit":
            assert sum(r[6] for r in crashed["published"]) == 3
        else:
            assert crashed["published"] == before["published"]
        if point in POINTS[:4]:
            committed = point == "after_ingest_commit"
            assert crashed["admitted_versions"] == before["admitted_versions"] + (
                5 if committed else 0
            )
            receipt = w.ingest(ROOT.joinpath("fixtures/05-web-corrections.json").read_bytes())
            assert receipt["replayed"] == committed
            recovered = w.reconcile()
            assert recovered["admitted_versions"] == before["admitted_versions"] + 5
            assert all(r["receipted"] for r in recovered["landing_objects"])
        else:
            expected = (
                "published"
                if point == "after_publish_commit"
                else "built"
                if point in ("after_build_commit", "before_publish_commit")
                else "planned"
            )
            assert w.run(run)["status"] == expected
            if "build" in point:
                w.build(run)
            w.publish(run)
            recovered = w.reconcile()
            assert recovered["active_run"] == run
            assert sum(r[6] for r in recovered["published"]) == 3
        return {
            "point": point,
            "process_exit_code": result.returncode,
            "publication_atomicity_passed": True,
            "versions_before": before["admitted_versions"],
            "versions_after_crash": crashed["admitted_versions"],
            "versions_after_retry": recovered["admitted_versions"],
            "active_before": before["active_run"],
            "active_after_crash": crashed["active_run"],
            "active_after_retry": recovered["active_run"],
            "recovery_passed": True,
        }


def execute(directory, output):
    results = [experiment(directory, point) for point in POINTS]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"experiments": results}, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return results
