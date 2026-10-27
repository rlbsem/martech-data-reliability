"""Single-writer control plane around the unchanged DuckDB publication engine."""

import base64
import json
import os
from pathlib import Path

from marketing_reliability.contracts import ContractError, canonical, digest, envelope
from marketing_reliability.warehouse import GateError, Warehouse

from .client import Client, Unknown
from .common import OWNERS, hash_value, now, single_writer, sqlite
from .oracle import variances, verify


class Operations:
    def __init__(self, config):
        self.config = config
        self.root = Path(config["state"])

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.guard = single_writer(self.root / "controller.lock")
        self.guard.__enter__()
        try:
            self.w = Warehouse(self.root / "warehouse")
            self.w.db.execute(Path(__file__).with_name("views.sql").read_text(encoding="utf-8"))
            with sqlite(self.root / "operations.sqlite") as c:
                c.executescript("""
                CREATE TABLE IF NOT EXISTS deliveries(service TEXT,seq INTEGER,metadata TEXT,sha TEXT,
                  state TEXT,reason TEXT,attempts INTEGER DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
                  PRIMARY KEY(service,seq));
                CREATE TABLE IF NOT EXISTS checkpoints(service TEXT PRIMARY KEY,seq INTEGER);
                CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,service TEXT,body TEXT,hash TEXT,observed TEXT);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,operation TEXT,body TEXT,observed TEXT);
                CREATE TRIGGER IF NOT EXISTS frozen_delivery BEFORE UPDATE OF service,seq,metadata,sha ON deliveries
                  BEGIN SELECT RAISE(ABORT,'immutable_delivery_identity'); END;
                """)
            with sqlite(self.root / "operations.sqlite") as c:
                for table in ["observations", "audit"]:
                    for action in ["UPDATE", "DELETE"]:
                        c.execute(
                            f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_operating_record'); END"
                        )
                c.execute(
                    "CREATE TRIGGER IF NOT EXISTS immutable_delivery_delete BEFORE DELETE ON deliveries BEGIN SELECT RAISE(ABORT,'immutable_delivery_identity'); END"
                )
            return self
        except BaseException:
            self.guard.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        self.w.close()
        self.guard.__exit__(*args)

    def event(self, operation, body):
        with sqlite(self.root / "operations.sqlite") as c:
            c.execute(
                "INSERT INTO audit(operation,body,observed) VALUES(?,?,?)",
                (operation, canonical(body), now()),
            )

    def observe(self, service):
        try:
            body = Client(self.config["sources"][service]).catalog()
        except Unknown as e:
            self.event("source_unknown", {"service": service, "reason": str(e)})
            raise
        with sqlite(self.root / "operations.sqlite") as c:
            # Even old checkpointed delivery identities must remain exact.
            known = c.execute(
                "SELECT seq,metadata FROM deliveries WHERE service=? ORDER BY seq", (service,)
            ).fetchall()
            for row in known:
                if (
                    row["seq"] > len(body["deliveries"])
                    or json.loads(row["metadata"]) != body["deliveries"][row["seq"] - 1]
                ):
                    raise Unknown("source_history_changed")
            c.execute(
                "INSERT INTO observations(service,body,hash,observed) VALUES(?,?,?,?)",
                (service, canonical(body), hash_value(body), now()),
            )
        return body

    def sync(self, service, crash=None):
        if service not in OWNERS:
            raise ValueError("unknown_owned_source")
        body, client = self.observe(service), Client(self.config["sources"][service])
        completed = []
        for entry in body["deliveries"]:
            with sqlite(self.root / "operations.sqlite") as c:
                checkpoint = c.execute(
                    "SELECT seq FROM checkpoints WHERE service=?", (service,)
                ).fetchone()
                if checkpoint and entry["seq"] <= checkpoint[0]:
                    continue
                row = c.execute(
                    "SELECT * FROM deliveries WHERE service=? AND seq=?", (service, entry["seq"])
                ).fetchone()
            path = self.root / "remote-landing" / (entry["sha256"] + ".bin")
            if row is None:
                raw = client.fetch(entry)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and digest(path.read_bytes()) != entry["sha256"]:
                    raise GateError("remote_landing_changed")
                if not path.exists():
                    temp = path.with_suffix(".tmp")
                    with temp.open("wb") as f:
                        f.write(raw)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(temp, path)
                with sqlite(self.root / "operations.sqlite") as c:
                    c.execute(
                        "INSERT INTO deliveries(service,seq,metadata,sha,state) VALUES(?,?,?,?,'fetched')",
                        (service, entry["seq"], canonical(entry), entry["sha256"]),
                    )
                if crash == "after_fetch":
                    os._exit(86)
            raw = path.read_bytes()
            if digest(raw) != entry["sha256"]:
                raise GateError("remote_landing_changed")
            try:
                parsed = envelope(raw)
            except ContractError:
                parsed = None  # Original engine retains and rejects the malformed envelope.
            if parsed and parsed["source"] != entry["feed"]:
                status, reason = "rejected", "source_ownership_denied"
            else:
                outcome = self.w.ingest(raw)
                status, reason = outcome["status"], outcome["reason"]
            if crash == "after_ingest":
                os._exit(86)
            with sqlite(self.root / "operations.sqlite") as c:
                c.execute(
                    "UPDATE deliveries SET state=?,reason=? WHERE service=? AND seq=?",
                    (status, reason, service, entry["seq"]),
                )
            # Historical acknowledgment recovery precedes any new POST.
            confirmed = None
            for _ in range(4):
                try:
                    confirmed = client.read_ack(entry)
                except Unknown:
                    self.event("ack_readback_unknown", {"service": service, "seq": entry["seq"]})
                    break
                if confirmed:
                    break
                with sqlite(self.root / "operations.sqlite") as c:
                    attempts = c.execute(
                        "SELECT attempts FROM deliveries WHERE service=? AND seq=?",
                        (service, entry["seq"]),
                    ).fetchone()[0]
                    if attempts >= 3:
                        break
                    c.execute(
                        "UPDATE deliveries SET attempts=attempts+1 WHERE service=? AND seq=?",
                        (service, entry["seq"]),
                    )
                try:
                    client.request("/v1/ack", {"seq": entry["seq"], "sha256": entry["sha256"]})
                except Unknown:
                    pass
            if not confirmed:
                self.event(
                    "ack_unresolved",
                    {"service": service, "seq": entry["seq"], "new_posts_bounded": 3},
                )
                raise Unknown("acknowledgment_not_independently_established")
            with sqlite(self.root / "operations.sqlite") as c:
                c.execute(
                    "INSERT INTO checkpoints VALUES(?,?) ON CONFLICT(service) DO UPDATE SET seq=excluded.seq",
                    (service, entry["seq"]),
                )
            self.event(
                "checkpoint_committed",
                {
                    "service": service,
                    "seq": entry["seq"],
                    "receipt": confirmed,
                    "warehouse_status": status,
                },
            )
            completed.append(entry["seq"])
        return completed

    def gates(self, start, through):
        pins, blockers = {}, []
        with sqlite(self.root / "operations.sqlite") as c:
            for service, feeds in OWNERS.items():
                try:
                    body = self.observe(service)
                except Unknown as e:
                    blockers.append({"source": service, "reason": str(e)})
                    continue
                pins[service] = hash_value(body)
                checkpoint = c.execute(
                    "SELECT seq FROM checkpoints WHERE service=?", (service,)
                ).fetchone()
                if (checkpoint[0] if checkpoint else 0) != len(body["deliveries"]):
                    blockers.append({"source": service, "reason": "uncheckpointed_source_delivery"})
                replaced = {n for e in body["deliveries"] for n in e["replaces"]}
                for row in c.execute(
                    "SELECT * FROM deliveries WHERE service=? AND state='rejected'", (service,)
                ):
                    if row["seq"] not in replaced:
                        blockers.append(
                            {
                                "source": service,
                                "reason": "unrepaired_rejected_delivery",
                                "seq": row["seq"],
                            }
                        )
                latest = {}
                for claim in body["claims"]:
                    if (
                        claim["id"] not in latest
                        or latest[claim["id"]]["revision"] < claim["revision"]
                    ):
                        latest[claim["id"]] = claim
                for feed in feeds:
                    claims = [v for v in latest.values() if v["feed"] == feed]
                    expected = [e["sha256"] for e in body["deliveries"] if e["feed"] == feed]
                    if len(claims) != 1:
                        blockers.append(
                            {"source": feed, "reason": "missing_or_conflicting_coverage_assertions"}
                        )
                    elif (
                        not claims[0]["complete"]
                        or claims[0]["start"] > start
                        or claims[0]["through"] < through
                    ):
                        blockers.append({"source": feed, "reason": "incomplete_reporting_period"})
                    elif claims[0]["delivery_hashes"] != expected:
                        blockers.append(
                            {
                                "source": feed,
                                "reason": "coverage_not_bound_to_exact_delivery_inventory",
                            }
                        )
        return pins, blockers

    def candidate(
        self,
        name,
        as_of="2026-09-04",
        start="2026-09-01",
        through="2026-09-03",
        full=False,
        dates=None,
        crash=None,
    ):
        old = self.w.rows("SELECT run_id FROM ops_candidates WHERE name=?", [name])
        if old:
            run = old[0][0]
            bounds = self.w.rows(
                "SELECT start_day,through_day FROM ops_candidates WHERE run_id=?", [run]
            )[0]
            if self.w.run(run)["as_of"] != as_of or bounds != [start, through]:
                raise GateError("candidate_request_identity_reused_with_different_coordinates")
            self.w.build(run, crash=crash)
            return run
        pins, gates = self.gates(start, through)
        accepted = [
            r[0]
            for r in self.w.rows(
                "SELECT hash FROM deliveries WHERE status='accepted' ORDER BY rowid"
            )
        ]
        run = self.w.plan(as_of, dates=dates, full=full)
        self.w.db.execute(
            "INSERT INTO ops_candidates VALUES(?,?,?,?,?,?,?)",
            [name, run, canonical(pins), canonical(accepted), canonical(gates), start, through],
        )
        self.w.build(run, crash=crash)
        self.event("candidate_built", {"name": name, "run": run, "gates": gates})
        return run

    def check(self, run):
        row = self.w.rows("SELECT accepted_hashes FROM ops_candidates WHERE run_id=?", [run])[0]
        return verify(self.w, run, json.loads(row[0]))

    def publish(self, run):
        row = self.w.rows(
            "SELECT pins,gates,start_day,through_day FROM ops_candidates WHERE run_id=?", [run]
        )[0]
        pins, blockers = self.gates(row[2], row[3])
        check = self.check(run)
        blockers += json.loads(row[1])
        if any(r[0] < row[2] or r[0] > row[3] for r in self.w.table(run)):
            blockers.append({"reason": "candidate_facts_outside_declared_reporting_interval"})
        if pins != json.loads(row[0]):
            blockers.append({"reason": "source_changed_since_candidate_pin"})
        if check["differences"] or check["unresolved"]:
            blockers.append(
                {
                    "reason": "independent_raw_source_reconciliation_failed",
                    "differences": check["differences"],
                    "unresolved": check["unresolved"],
                }
            )
        if blockers:
            self.event("publication_blocked", {"run": run, "findings": blockers})
            raise GateError(canonical(blockers))
        self.w.publish(run)
        self.event(
            "published", {"run": run, "table_sha256": check["table_sha256"], "source_pins": pins}
        )
        return check

    def snapshot(self):
        with sqlite(self.root / "operations.sqlite") as c:
            journal = {
                t: [dict(r) for r in c.execute("SELECT * FROM " + t)]
                for t in ["deliveries", "checkpoints", "observations", "audit"]
            }
        candidates = []
        for name, run in self.w.rows("SELECT name,run_id FROM ops_candidates ORDER BY run_id"):
            candidates.append(
                {
                    "name": name,
                    "run": self.w.run(run),
                    "table": self.w.table(run),
                    "raw_oracle": self.check(run),
                    "source_variances": variances(self.w, run),
                    "lineage": self.w.lineage(run),
                }
            )
        return {
            "synthetic": True,
            "currency": "USD",
            "native_vendor_execution": False,
            "journal": journal,
            "candidates": candidates,
            "warehouse": self.w.reconcile(),
            "retained_remote_deliveries": [
                {
                    "service": r["service"],
                    "seq": r["seq"],
                    "sha256": r["sha"],
                    "utf8_display": (self.root / "remote-landing" / (r["sha"] + ".bin"))
                    .read_bytes()
                    .decode("utf-8", errors="replace"),
                    "exact_base64": base64.b64encode(
                        (self.root / "remote-landing" / (r["sha"] + ".bin")).read_bytes()
                    ).decode(),
                    "warehouse_receipt": self.w.receipt(r["sha"]),
                }
                for r in journal["deliveries"]
            ],
            "opportunity_day": self.w.rows(
                "SELECT * FROM ops_opportunity_day ORDER BY run_id,day,campaign_id"
            ),
        }
