"""Bounded HTTP service, safe request telemetry and current read-only readiness."""

import json
import threading
import time
import uuid
from http.server import ThreadingHTTPServer

from .common import hash_value, now


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # No raw URL, headers, remote address, exception text or traceback in logs.
        print(json.dumps({"at": now(), "event": "request_failed"}), flush=True)


def request_identity(handler):
    handler.request_id = uuid.uuid4().hex
    handler.request_started = time.monotonic()


def response_headers(handler, status, service):
    request_id = getattr(handler, "request_id", None)
    if request_id is None:
        request_identity(handler)
    handler.send_header("X-Request-ID", handler.request_id)
    handler.send_header("Referrer-Policy", "no-referrer")
    # Schema allowlist: client-controlled fields and exception messages never enter logs.
    route = handler.path.split("?", 1)[0]
    if route not in {
        "/",
        "/health",
        "/livez",
        "/readyz",
        "/api/state",
        "/api/operations",
        "/api/ack",
        "/api/raw",
        "/v1/catalog",
        "/v1/ack",
        "/app.js",
        "/style.css",
    }:
        route = "other"
    print(
        json.dumps(
            {
                "at": now(),
                "event": "http_response",
                "service": service,
                "request_id": handler.request_id,
                "route": route,
                "status": status,
                "duration_ms": round((time.monotonic() - handler.request_started) * 1000, 2),
            }
        ),
        flush=True,
    )


def readiness(config):
    """No writes. Failure retains inspection access but prevents readiness admission.

    Source inventory is observed sequentially, never a distributed snapshot. Financial
    freshness uses the recorded business date, not a fictional present-day live feed.
    """
    from .view import state, verify_live

    try:
        if not __debug__:
            raise ValueError("optimized_python_not_supported")
        verified = verify_live(config)
        body = state(config)
        active = next(c for c in body["candidates"] if c["run"]["id"] == verified["active_run"])
        if active["run"]["status"] != "published":
            raise ValueError("publication_not_active")
        with_inventory = {
            name: source["sha256"]
            for name, source in body["sources"].items()
            if source["status"] == "observed"
        }
        if len(with_inventory) != 3:
            raise ValueError("source_unavailable")
        # Active publication pins include completeness claims, not just delivery counts.
        import duckdb
        from pathlib import Path

        with duckdb.connect(
            str(Path(config["state"]) / "warehouse/warehouse.duckdb"), read_only=True
        ) as db:
            pins = json.loads(
                db.execute(
                    "SELECT pins FROM ops_candidates WHERE run_id=?", [verified["active_run"]]
                ).fetchone()[0]
            )
        if pins != with_inventory:
            raise ValueError("source_inventory_changed_since_publication")
        return {
            "status": "ready",
            "observed_at": now(),
            "read_only": True,
            "synthetic": True,
            "active_run": verified["active_run"],
            "independent_receipts": verified["independent_source_receipts"],
            "source_inventory_sha256": hash_value(with_inventory),
            "source_checkpoints": body["journal"]["checkpoints"],
            "source_row_accounting": verified["source_row_accounting"],
            "totals": verified["totals"],
            "historical_candidates": len(body["candidates"]),
            "unpublished_candidates": sum(
                c["run"]["status"] != "published" for c in body["candidates"]
            ),
            "reporting_as_of": active["run"]["as_of"],
            "freshness_boundary": "recorded_business_date_not_live_source_SLA",
        }
    except Exception:
        return {
            "status": "not_ready",
            "observed_at": now(),
            "read_only": True,
            "synthetic": True,
            "reason": "dependency_publication_or_independent_verification_failed",
            "inspection_may_remain_available": True,
        }
