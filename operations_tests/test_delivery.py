import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml

from conftest import console
from reliability_ops.backup import backup, restore, validate
from reliability_ops.common import single_writer, sqlite
from reliability_ops.operational import BoundedServer, readiness, response_headers
from reliability_ops.source import claim


def readonly(runtime):
    return json.loads((runtime.root / "console.json").read_bytes())


def test_readiness_checks_independent_arithmetic_and_declared_freshness(baseline):
    report = readiness(readonly(baseline))
    assert report["status"] == "ready"
    assert report["active_run"] == baseline.baseline
    assert report["totals"]["cost_cents"] == 36000
    assert report["freshness_boundary"] == "recorded_business_date_not_live_source_SLA"


def test_changed_coverage_without_new_deliveries_is_not_ready(baseline):
    claim(baseline.source_configs["website"], "web", 2, complete=False)
    assert readiness(readonly(baseline))["status"] == "not_ready"


def test_liveness_survives_dependency_outage_without_claiming_readiness(baseline):
    url = console(baseline)
    with sqlite(baseline.source_configs["website"]["db"]) as c:
        c.execute("UPDATE faults SET mode='outage'")
    assert urlopen(url + "livez").status == 200
    with pytest.raises(HTTPError) as e:
        urlopen(url + "readyz")
    assert e.value.code == 503
    assert json.loads(e.value.read())["status"] == "not_ready"
    assert json.load(urlopen(url + "api/state"))["warehouse"]["active_run"] == baseline.baseline


def test_quiescent_backup_restore_preserves_independent_values_and_never_overwrites(baseline):
    config = readonly(baseline)
    archive = baseline.root / "backup"
    assert backup(config, archive)["status"] == "passed"
    result = restore(config, archive, baseline.root / "restored")
    assert result["status"] == "passed" and result["source_writes"] == 0
    assert result["automatic_controller_resume"] is False
    assert result["totals"] == readiness(config)["totals"]
    assert "read_token" not in (archive / "manifest.json").read_text()
    with pytest.raises(ValueError, match="empty_destination"):
        restore(config, archive, baseline.root / "restored")


def test_backup_refuses_active_controller_and_existing_archive(baseline):
    config = readonly(baseline)
    with single_writer(baseline.root / "state/controller.lock"):
        with pytest.raises(RuntimeError, match="writer_lock"):
            backup(config, baseline.root / "busy-backup")
    with pytest.raises(ValueError, match="fresh_backup"):
        backup(config, baseline.root)


def test_tampered_backup_and_added_files_are_rejected_before_restore(baseline):
    archive = baseline.root / "backup"
    backup(readonly(baseline), archive)
    (archive / "extra.txt").write_text("unexpected")
    with pytest.raises(ValueError, match="backup_content_changed"):
        validate(archive)
    (archive / "extra.txt").unlink()
    manifest = json.loads((archive / "manifest.json").read_bytes())
    path = archive / next(iter(manifest["files"]))
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="backup_content_changed"):
        restore(readonly(baseline), archive, baseline.root / "never-created")
    assert not (baseline.root / "never-created").exists()


def test_restore_against_remote_ahead_inventory_fails_closed(baseline):
    config = readonly(baseline)
    archive = baseline.root / "backup"
    backup(config, archive)
    claim(baseline.source_configs["website"], "web", 2, complete=False)
    with pytest.raises(ValueError, match="independent_sources"):
        restore(config, archive, baseline.root / "held-restore")
    assert (baseline.root / "held-restore").exists()  # diagnostic copy, never activated
    assert config["state"] == str(baseline.root / "state")


def test_readiness_detects_raw_input_corruption_without_rewriting_publication(baseline):
    root = baseline.root / "state/warehouse/landing"
    path = next(root.glob("*.json"))
    original = path.read_bytes()
    path.write_bytes(b"{}")
    assert readiness(readonly(baseline))["status"] == "not_ready"
    path.write_bytes(original)
    assert readiness(readonly(baseline))["status"] == "ready"


def test_logs_use_server_generated_ids_and_never_capture_query_headers_or_addresses(capsys):
    class Handler:
        path = "/api/raw?secret=private-value"
        headers = {"Authorization": "Bearer private-value", "X-Request-ID": "untrusted"}

        def send_header(self, *_):
            pass

    response_headers(Handler(), 403, "console")
    log = json.loads(capsys.readouterr().out)
    assert len(log["request_id"]) == 32
    assert log["route"] == "/api/raw"
    assert "private-value" not in json.dumps(log) and "untrusted" not in json.dumps(log)


def test_mutation_origin_and_host_boundaries_stay_denied(baseline):
    url = console(baseline)
    for method in ["POST", "PUT", "PATCH", "DELETE"]:
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "api/operations", data=b"{}", method=method))
        assert error.value.code == 405
    for headers in [{"Host": "attacker.example"}, {"Origin": "https://attacker.example"}]:
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url + "api/state", headers=headers))
        assert error.value.code == 403


def test_server_admission_is_bounded():
    from http.server import BaseHTTPRequestHandler

    with BoundedServer(("127.0.0.1", 0), BaseHTTPRequestHandler) as server:
        for _ in range(16):
            assert server.slots.acquire(blocking=False)
        assert not server.slots.acquire(blocking=False)
        for _ in range(16):
            server.slots.release()


def test_container_override_has_limits_and_no_new_public_or_mutating_service():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    body = yaml.safe_load((root / "deploy/compose.acceptance.yaml").read_text())
    for service in body["services"].values():
        assert service["cpus"] == 1.0
        assert "ports" not in service
        assert service["logging"]["options"]["max-size"] == "5m"
    assert "@sha256:" in (root / "Dockerfile").read_text()
    assert "--require-hashes" in (root / "Dockerfile").read_text()


def test_service_startup_rejects_write_credentials_in_console_and_shared_source_tokens(baseline):
    from reliability_ops.service import validate_config

    config = readonly(baseline)
    validate_config(config, "console")
    config["sources"]["crm"]["ack_token"] = "should-not-be-mounted"
    with pytest.raises(ValueError, match="read_only_source_identity"):
        validate_config(config, "console")
    source = {**baseline.source_configs["crm"]}
    validate_config(source, "source")
    source["ack_token"] = source["read_token"]
    with pytest.raises(ValueError, match="distinct_strong"):
        validate_config(source, "source")
