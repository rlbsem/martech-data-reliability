"""One serialized local writer; durable receipt, pinned build and atomic publication."""

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import duckdb

from .contracts import (
    METRICS,
    SOURCES,
    ContractError,
    canonical,
    day,
    digest,
    envelope,
    implementation_hash,
    record,
)
from .oracle import aggregate

SQL = Path(__file__).parent / "sql"


class GateError(ValueError):
    pass


def fail(point, selected):
    if point == selected:
        os._exit(86)  # Actual abrupt process death, including uncommitted DuckDB work.


class Warehouse:
    def __init__(self, directory):
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.landing = self.root / "landing"
        self.landing.mkdir(exist_ok=True)
        self.db = duckdb.connect(str(self.root / "warehouse.duckdb"))
        self.db.execute(SQL.joinpath("schema.sql").read_text(encoding="utf-8"))

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def rows(self, sql, args=None):
        return [list(row) for row in self.db.execute(sql, args or []).fetchall()]

    def _land(self, raw):
        checksum = digest(raw)
        target = self.landing / f"{checksum}.json"
        if target.exists():
            if digest(target.read_bytes()) != checksum:
                raise GateError("landing object changed; restore original bytes")
        else:
            # Same-directory atomic rename exposes only a completely flushed object.
            # A terminated writer can leave an unreferenced .tmp file, safe to ignore.
            with tempfile.NamedTemporaryFile(
                dir=self.landing, suffix=".tmp", delete=False
            ) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = handle.name
            os.replace(temporary, target)
        return checksum

    def receipt(self, checksum):
        row = self.db.execute("SELECT * FROM deliveries WHERE hash = ?", [checksum]).fetchone()
        if row is None:
            return None
        return dict(
            zip(("hash", "source", "batch_id", "status", "reason", "coverage", "row_count"), row)
        )

    def ingest(self, raw, crash=None):
        checksum = self._land(raw)
        fail("after_landing", crash)
        old = self.receipt(checksum)
        if old:
            return {**old, "replayed": True}
        try:
            batch = envelope(raw)
        except ContractError as error:
            return self._reject(checksum, str(error))
        source, batch_id = batch["source"], batch["batch_id"]
        if self.db.execute(
            "SELECT 1 FROM deliveries WHERE source=? AND batch_id=?", [source, batch_id]
        ).fetchone():
            return self._reject(checksum, "batch identity reused with different bytes")
        try:
            with self.transaction():
                for line, raw_row in enumerate(batch["rows"], 1):
                    try:
                        value = record(source, batch["schema_version"], raw_row)
                        if value.get("day", batch["covered_through"]) > batch["covered_through"]:
                            raise ContractError("row date exceeds declared delivery coverage")
                    except ContractError as error:
                        self._row(checksum, line, "quarantined", str(error), raw_row)
                        continue
                    payload = canonical(value)
                    prior = self.db.execute(
                        "SELECT payload FROM versions WHERE source=? AND id=? AND revision=?",
                        [source, value["id"], value["revision"]],
                    ).fetchone()
                    if prior:
                        if prior[0] != payload:
                            raise GateError("same source/id/revision has conflicting meaning")
                        self._row(checksum, line, "duplicate", None, raw_row)
                        continue
                    old_day = self.db.execute(
                        "SELECT day FROM latest WHERE source=? AND id=?", [source, value["id"]]
                    ).fetchone()
                    self.db.execute(
                        "INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [
                            source,
                            value["id"],
                            value["revision"],
                            value["op"],
                            value.get("day"),
                            value.get("campaign_id"),
                            *[value.get(m) for m in METRICS],
                            value.get("name"),
                            payload,
                            checksum,
                            line,
                        ],
                    )
                    dirty = {value.get("day"), old_day[0] if old_day else None} - {None}
                    if source == "campaigns":
                        dirty.update(
                            r[0]
                            for r in self.rows(
                                "SELECT DISTINCT day FROM versions WHERE day IS NOT NULL"
                            )
                        )
                    for date_key in dirty:
                        self.db.execute(
                            "INSERT INTO dirty VALUES (?) ON CONFLICT DO NOTHING", [date_key]
                        )
                    self._row(checksum, line, "admitted", None, raw_row)
                    fail("during_ingest", crash)
                self.db.execute(
                    "INSERT INTO deliveries VALUES (?,?,?,'accepted',NULL,?,?)",
                    [checksum, source, batch_id, batch["covered_through"], len(batch["rows"])],
                )
                self.db.execute(
                    "INSERT INTO coverage VALUES (?,?) ON CONFLICT(source) DO UPDATE SET through_day=greatest(coverage.through_day,excluded.through_day)",
                    [source, batch["covered_through"]],
                )
                self.db.execute("UPDATE meta SET epoch=epoch+1")
                fail("before_ingest_commit", crash)
            fail("after_ingest_commit", crash)
        except GateError as error:
            return self._reject(checksum, str(error), len(batch["rows"]))
        return {**self.receipt(checksum), "replayed": False}

    def _row(self, checksum, line, disposition, reason, raw):
        self.db.execute(
            "INSERT INTO row_receipts VALUES (?,?,?,?,?)",
            [checksum, line, disposition, reason, canonical(raw)],
        )

    def _reject(self, checksum, reason, count=0):
        self.db.execute(
            "INSERT INTO deliveries VALUES (?,NULL,NULL,'rejected',?,NULL,?)",
            [checksum, reason, count],
        )
        return {**self.receipt(checksum), "replayed": False}

    def plan(self, as_of, dates=None, full=False):
        day(as_of)
        if dates is not None and full:
            raise GateError("choose explicit dates or full rebuild")
        with self.transaction():
            epoch, base = self.db.execute("SELECT epoch, active_run FROM meta").fetchone()
            if dates is None:
                dates = [r[0] for r in self.rows("SELECT day FROM dirty")]
            if full or base is None:
                dates = sorted(
                    set(dates)
                    | {
                        r[0]
                        for r in self.rows(
                            "SELECT day FROM versions WHERE day IS NOT NULL UNION SELECT day FROM mart WHERE run_id=?",
                            [base],
                        )
                    }
                )
            dates = sorted({day(d) for d in dates})
            run_id = self.db.execute("SELECT coalesce(max(id),0)+1 FROM runs").fetchone()[0]
            self.db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,'planned',NULL)",
                [run_id, epoch, base, as_of, implementation_hash(), canonical(dates)],
            )
            self.db.execute("INSERT INTO run_inputs SELECT ?, * FROM latest", [run_id])
            self.db.execute("INSERT INTO run_coverage SELECT ?, * FROM coverage", [run_id])
        return run_id

    def run(self, run_id):
        row = self.db.execute("SELECT * FROM runs WHERE id=?", [run_id]).fetchone()
        if row is None:
            raise GateError("unknown run")
        result = dict(
            zip(
                ("id", "epoch", "base", "as_of", "implementation", "scope", "status", "evidence"),
                row,
            )
        )
        result["scope"] = json.loads(result["scope"])
        result["evidence"] = json.loads(result["evidence"]) if result["evidence"] else None
        return result

    def build(self, run_id, crash=None):
        run = self.run(run_id)
        if run["implementation"] != implementation_hash():
            raise GateError("implementation changed; plan a new run")
        if run["status"] != "planned":
            return run
        with self.transaction():
            self.db.execute(
                "INSERT INTO mart SELECT ?, * EXCLUDE (run_id) FROM mart WHERE run_id=? AND day NOT IN (SELECT unnest(?::VARCHAR[]))",
                [run_id, run["base"], run["scope"]],
            )
            computed = self.db.execute(
                SQL.joinpath("campaign_daily.sql").read_text(encoding="utf-8"),
                [run_id, run["scope"], run_id],
            ).fetchall()
            if computed:
                self.db.executemany(
                    "INSERT INTO mart VALUES (?,?,?,?,?,?,?,?,?)",
                    [[run_id, *row] for row in computed],
                )
            fail("during_build", crash)
            evidence = self.validate(run_id)
            self.db.execute(
                "UPDATE runs SET status='built', evidence=? WHERE id=?",
                [canonical(evidence), run_id],
            )
        fail("after_build_commit", crash)
        return self.run(run_id)

    def table(self, run_id=None):
        if run_id is None:
            return self.rows("SELECT * FROM published_campaign_daily ORDER BY day, campaign_id")
        return self.rows(
            "SELECT * EXCLUDE (run_id) FROM mart WHERE run_id=? ORDER BY day, campaign_id", [run_id]
        )

    def validate(self, run_id):
        run = self.run(run_id)
        inputs = [
            (source, json.loads(payload))
            for source, payload in self.rows(
                "SELECT source,payload FROM run_inputs WHERE run_id=? ORDER BY source,id", [run_id]
            )
        ]
        expected, unresolved = aggregate(inputs)
        actual = self.table(run_id)
        blockers = []
        if actual != expected:
            blockers.append("candidate differs from independent full aggregation")
        if unresolved:
            blockers.append("unresolved campaign references")
        coverage = dict(
            self.rows("SELECT source,through_day FROM run_coverage WHERE run_id=?", [run_id])
        )
        lags = {}
        for source in SOURCES:
            lag = (
                (date.fromisoformat(run["as_of"]) - date.fromisoformat(coverage[source])).days
                if source in coverage
                else None
            )
            lags[source] = lag
            if lag is None or not 0 <= lag <= 1:
                blockers.append(f"coverage outside 0..1 day freshness window: {source}")
        return {
            "blockers": blockers,
            "unresolved": unresolved,
            "coverage_lag_days": lags,
            "independent_full_match": actual == expected,
            "row_count": len(actual),
            "table_sha256": digest(canonical(actual).encode()),
            "totals": {name: sum(row[i + 3] for row in actual) for i, name in enumerate(METRICS)},
        }

    def publish(self, run_id, crash=None):
        run = self.run(run_id)
        if run["status"] == "published":
            return run  # Never reactivate an older successful run on retry.
        with self.transaction():
            epoch, active = self.db.execute("SELECT epoch,active_run FROM meta").fetchone()
            if run["status"] != "built" or epoch != run["epoch"] or active != run["base"]:
                raise GateError("unbuilt or stale plan; ingestion/publication changed")
            if run["implementation"] != implementation_hash():
                raise GateError("implementation changed; plan a new run")
            evidence = self.validate(run_id)
            if evidence["blockers"]:
                raise GateError("; ".join(evidence["blockers"]))
            if evidence != run["evidence"]:
                raise GateError("candidate changed after validation")
            self.db.execute("UPDATE meta SET active_run=?", [run_id])
            self.db.execute(
                "DELETE FROM dirty WHERE day IN (SELECT unnest(?::VARCHAR[]))", [run["scope"]]
            )
            self.db.execute("UPDATE runs SET status='published' WHERE id=?", [run_id])
            fail("before_publish_commit", crash)
        fail("after_publish_commit", crash)
        return self.run(run_id)

    def reconcile(self):
        deliveries = self.rows(
            "SELECT hash,source,batch_id,status,reason,coverage,row_count FROM deliveries ORDER BY hash"
        )
        counts = dict(
            self.rows("SELECT disposition,count(*) FROM row_receipts GROUP BY disposition")
        )
        accepted_count = sum(row[6] for row in deliveries if row[3] == "accepted")
        if accepted_count != sum(counts.values()):
            raise GateError("receipt conservation failed")
        admitted = self.db.execute("SELECT count(*) FROM versions").fetchone()[0]
        latest = self.db.execute("SELECT count(*) FROM latest").fetchone()[0]
        tombstones = self.db.execute("SELECT count(*) FROM latest WHERE op='delete'").fetchone()[0]
        if counts.get("admitted", 0) != admitted:
            raise GateError("version conservation failed")
        objects = []
        for receipt in deliveries:
            if not (self.landing / f"{receipt[0]}.json").is_file():
                raise GateError("receipted landing object missing")
            if receipt[3] == "accepted":
                observed = self.db.execute(
                    "SELECT count(*) FROM row_receipts WHERE hash=?", [receipt[0]]
                ).fetchone()[0]
                if observed != receipt[6]:
                    raise GateError("per-delivery receipt conservation failed")
        for path in sorted(self.landing.glob("*.json")):
            if digest(path.read_bytes()) != path.stem:
                raise GateError("landing checksum mismatch")
            objects.append({"sha256": path.stem, "receipted": self.receipt(path.stem) is not None})
        active = self.db.execute("SELECT active_run FROM meta").fetchone()[0]
        return {
            "accepted_delivery_rows": accepted_count,
            "row_dispositions": counts,
            "admitted_versions": admitted,
            "superseded_versions": admitted - latest,
            "current_tombstones": tombstones,
            "current_live_records": latest - tombstones,
            "deliveries": deliveries,
            "landing_objects": objects,
            "quarantine": self.rows(
                "SELECT hash,line,reason,raw FROM row_receipts WHERE disposition='quarantined' ORDER BY hash,line"
            ),
            "active_run": active,
            "published": self.table(),
            "active_run_validation": self.validate(active) if active is not None else None,
            "dirty_dates": [row[0] for row in self.rows("SELECT day FROM dirty ORDER BY day")],
        }

    def lineage(self, run_id):
        # Includes unresolved inputs and tombstones, not merely successful report rows.
        return self.rows(
            "SELECT source,id,revision,op,day,campaign_id,hash,line FROM run_inputs WHERE run_id=? ORDER BY source,id",
            [run_id],
        )
