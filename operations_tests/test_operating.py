import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

from marketing_reliability.contracts import canonical
from marketing_reliability.warehouse import GateError
from reliability_ops.client import Client, Unknown
from reliability_ops.common import OWNERS, sqlite
from reliability_ops.controller import Operations
from reliability_ops.demo import execute
from reliability_ops.scenario import raw_fixture
from reliability_ops.source import append, claim
from reliability_ops.view import verify_live

from conftest import console


def test_complete_native_http_process_recovery_and_independent_arithmetic(runtime):
    report = execute(runtime.config, runtime.source_configs, runtime.root / "controller.json")
    assert len(report["checks"]) == 30 and all(c["passed"] for c in report["checks"])
    check = verify_live(json.loads((runtime.root / "console.json").read_bytes()))
    assert check["totals"]["cost_cents"] == 41000
    assert check["totals"]["conversions"] == 6
    assert check["totals"]["revenue_cents"] == 115000
    assert check["read_only"] and check["independent_source_receipts"] >= 10
    # Ordinary repeated demonstration returns stored actual evidence, never repeats writes.
    assert (
        execute(runtime.config, runtime.source_configs, runtime.root / "controller.json") == report
    )


def test_exact_transport_replay_has_distinct_source_receipt_but_no_new_versions(baseline):
    append(baseline.source_configs["website"], "web", raw_fixture(3))
    claim(baseline.source_configs["website"], "web", 2)
    with Operations(baseline.config) as ops:
        before = ops.w.reconcile()["admitted_versions"]
        assert ops.sync("website") == [2]
        assert ops.w.reconcile()["admitted_versions"] == before
        assert ops.sync("website") == []
    with sqlite(baseline.source_configs["website"]["db"]) as c:
        assert c.execute("SELECT count(*) FROM acknowledgments").fetchone()[0] == 2


@pytest.mark.parametrize("mode,posts", [("unknown_ack", 0), ("reject_ack", 3)])
def test_uncertain_ack_is_not_absence_and_new_post_budget_is_durable(runtime, mode, posts):
    append(runtime.source_configs["website"], "web", raw_fixture(3))
    with sqlite(runtime.source_configs["website"]["db"]) as c:
        c.execute("UPDATE faults SET mode=?", (mode,))
    for _ in range(2):
        with Operations(runtime.config) as ops:
            with pytest.raises(Unknown):
                ops.sync("website")
    with sqlite(runtime.source_configs["website"]["db"]) as c:
        assert c.execute("SELECT count(*) FROM requests").fetchone()[0] == posts
        assert c.execute("SELECT count(*) FROM acknowledgments").fetchone()[0] == 0
    with sqlite(Path(runtime.config["state"]) / "operations.sqlite") as c:
        assert c.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0


def test_foreign_owned_feed_never_enters_warehouse(runtime):
    append(runtime.source_configs["website"], "web", raw_fixture(4))
    with Operations(runtime.config) as ops:
        assert ops.sync("website") == [1]
        assert ops.w.rows("SELECT count(*) FROM versions") == [[0]]
        _, findings = ops.gates("2026-09-01", "2026-09-03")
        assert any(f["reason"] == "unrepaired_rejected_delivery" for f in findings)
    with sqlite(Path(runtime.config["state"]) / "operations.sqlite") as c:
        assert c.execute("SELECT reason FROM deliveries").fetchone()[0] == "source_ownership_denied"


def test_wrong_bytes_cannot_advance_checkpoint_or_admission(runtime):
    append(runtime.source_configs["website"], "web", raw_fixture(3))
    with sqlite(runtime.source_configs["website"]["db"]) as c:
        c.execute("UPDATE faults SET mode='corrupt_body'")
    with Operations(runtime.config) as ops:
        with pytest.raises(Unknown, match="not_verified"):
            ops.sync("website")
        assert ops.w.rows("SELECT count(*) FROM versions") == [[0]]


@pytest.mark.parametrize("kind", ["incomplete", "conflict", "unbound"])
def test_coverage_assertions_gate_without_replacing_verified_report(baseline, kind):
    conf = baseline.source_configs["website"]
    if kind == "incomplete":
        claim(conf, "web", 2, complete=False)
    elif kind == "conflict":
        claim(conf, "web", 1, complete=False, key="contradictory-authority")
    else:
        append(conf, "web", raw_fixture(3))
    with Operations(baseline.config) as ops:
        if kind == "unbound":
            ops.sync("website")
        old = ops.w.table()
        run = ops.candidate("coverage-" + kind)
        with pytest.raises(GateError):
            ops.publish(run)
        assert ops.w.table() == old


def test_source_update_after_pin_blocks_publication_before_warehouse_ingestion(baseline):
    with Operations(baseline.config) as ops:
        run = ops.candidate("before-external-change")
        append(baseline.source_configs["website"], "web", raw_fixture(5))
        with pytest.raises(GateError, match="source_changed"):
            ops.publish(run)
        assert ops.w.run(run)["status"] == "built"
        assert ops.w.rows("SELECT active_run FROM meta") == [[baseline.baseline]]


def test_equal_row_count_corruption_has_exact_value_differences_and_no_publication(baseline):
    with Operations(baseline.config) as ops:
        run = ops.candidate("wrong-values")
        before = ops.w.table(run)
        ops.w.db.execute(
            "UPDATE mart SET cost_cents=cost_cents+1 WHERE run_id=? AND campaign_id='search'", [run]
        )
        check = ops.check(run)
        assert len(check["actual"]) == len(before) and check["differences"]
        assert all(d["actual"][3] - d["expected"][3] == 1 for d in check["differences"])
        with pytest.raises(GateError, match="independent_raw_source"):
            ops.publish(run)


def test_independent_oracle_catches_latest_revision_and_lineage_corruption(baseline):
    with Operations(baseline.config) as ops:
        run = ops.candidate("bad-lineage")
        ops.w.db.execute(
            "UPDATE run_inputs SET line=line+1 WHERE run_id=? AND source='web' AND id='w1'", [run]
        )
        with pytest.raises(AssertionError, match="latest_revision_or_lineage"):
            ops.check(run)


def test_reporting_coverage_cannot_be_narrower_than_reported_facts(baseline):
    with Operations(baseline.config) as ops:
        run = ops.candidate("narrow", start="2026-09-02")
        with pytest.raises(GateError, match="outside_declared_reporting_interval"):
            ops.publish(run)


def test_candidate_name_cannot_alias_different_reporting_coordinates(baseline):
    with Operations(baseline.config) as ops:
        with pytest.raises(GateError, match="identity_reused"):
            ops.candidate("baseline", as_of="2026-09-05")


def test_second_controller_is_refused_instead_of_racing_checkpoints(baseline):
    with Operations(baseline.config):
        with pytest.raises(RuntimeError, match="another_controller"):
            with Operations(baseline.config):
                raise AssertionError("second_writer_entered")


def test_source_and_controller_journal_identities_are_immutable(baseline):
    with sqlite(baseline.source_configs["website"]["db"]) as c:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("UPDATE deliveries SET raw=X'00' WHERE seq=1")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("DELETE FROM acknowledgments")
    with sqlite(Path(baseline.config["state"]) / "operations.sqlite") as c:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("UPDATE deliveries SET sha='changed' WHERE service='website'")


def test_source_read_credential_cannot_commit_acknowledgment(runtime):
    append(runtime.source_configs["website"], "web", raw_fixture(3))
    config = runtime.config["sources"]["website"]
    req = Request(
        config["url"] + "/v1/ack",
        data=b"{}",
        headers={"Authorization": "Bearer " + config["read_token"]},
    )
    with pytest.raises(HTTPError) as error:
        urlopen(req)
    assert error.value.code == 403


@pytest.mark.parametrize(
    "url",
    [
        "https://vendor.example.com",
        "http://169.254.169.254",
        "http://user:pass@localhost",
        "http://localhost/?secret=x",
    ],
)
def test_source_endpoints_do_not_allow_arbitrary_external_destinations(url):
    with pytest.raises(ValueError, match="isolated_source"):
        Client({"url": url})


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"contract": 1},
        {"contract": 1, "service": "advertising", "deliveries": [], "claims": []},
    ],
)
def test_malformed_or_wrong_owner_http_200_catalog_is_unknown(runtime, body):
    client = Client(runtime.config["sources"]["website"])
    client.request = lambda *_: (200, canonical(body).encode())
    with pytest.raises(Unknown):
        client.catalog()


def test_console_is_read_only_and_exposes_exact_sources_without_credentials(baseline):
    url = console(baseline)
    with urlopen(url + "api/state") as r:
        body = json.load(r)
    assert body["read_only"] and body["warehouse"]["active_run"] == baseline.baseline
    assert all(
        c["read_token"] not in json.dumps(body) and c["ack_token"] not in json.dumps(body)
        for c in baseline.config["sources"].values()
    )
    for path in ["api/publish", "api/sync", "api/ack"]:
        with pytest.raises(HTTPError) as e:
            urlopen(Request(url + path, data=b"{}"))
        assert e.value.code == 405
    with urlopen(url + "api/ack?service=website&seq=1") as r:
        assert json.load(r)["checkpoint_changed"] is False
    with pytest.raises(HTTPError) as e:
        urlopen(url + "private/controller.json")
    assert e.value.code == 404


def test_source_outage_console_keeps_verified_report_but_labels_unknown(baseline):
    url = console(baseline)
    with sqlite(baseline.source_configs["website"]["db"]) as c:
        c.execute("UPDATE faults SET mode='outage'")
    with urlopen(url + "api/state") as r:
        body = json.load(r)
    assert body["sources"]["website"]["status"] == "unknown"
    assert body["warehouse"]["active_run"] == baseline.baseline


def test_original_engine_fixtures_tests_and_evidence_are_preserved():
    root = Path(__file__).parents[1]
    inventory = json.loads((root / "docs/evidence/operations/original-files.json").read_bytes())
    assert all(
        hashlib.sha256((root / p).read_bytes()).hexdigest() == h
        for p, h in inventory["sha256"].items()
    )


def test_compose_exposes_only_console_and_scopes_storage():
    root = Path(__file__).parents[1]
    compose = yaml.safe_load((root / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["console"]["ports"] == ["127.0.0.1:8602:8602"]
    assert all("ports" not in s for n, s in services.items() if n != "console")
    assert compose["networks"]["backend"]["internal"]
    assert services["console"]["volumes"] == [
        "state:/state:ro",
        "console-config:/console-config:ro",
    ]
    assert all(
        s["tmpfs"] == ["/tmp:size=128m,mode=1777"] and s["cap_drop"] == ["ALL"] and s["read_only"]
        for s in services.values()
    )
    for name in OWNERS:
        assert services[name]["volumes"] == [name + "-data:/sources/" + name]
