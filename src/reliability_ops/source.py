"""Three independently persisted synthetic services, each with a finite HTTP contract."""

import hmac
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from marketing_reliability.contracts import digest, identifier

from .common import LIMIT, OWNERS, hash_value, now, sqlite
from .operational import BoundedServer, request_identity, response_headers


def initialize(path):
    with sqlite(path) as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS deliveries(seq INTEGER PRIMARY KEY, feed TEXT NOT NULL,
          sha TEXT NOT NULL,raw BLOB NOT NULL,replaces_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS claims(id TEXT,revision INTEGER,body TEXT NOT NULL,
          PRIMARY KEY(id,revision));
        CREATE TABLE IF NOT EXISTS acknowledgments(seq INTEGER PRIMARY KEY,body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY,operation TEXT,seq INTEGER,result TEXT,observed TEXT);
        CREATE TABLE IF NOT EXISTS faults(id INTEGER PRIMARY KEY CHECK(id=1),mode TEXT NOT NULL);
        INSERT OR IGNORE INTO faults VALUES(1,'none');
        CREATE TRIGGER IF NOT EXISTS immutable_delivery BEFORE UPDATE ON deliveries BEGIN SELECT RAISE(ABORT,'immutable_delivery'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_claim BEFORE UPDATE ON claims BEGIN SELECT RAISE(ABORT,'immutable_claim'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_ack BEFORE UPDATE ON acknowledgments BEGIN SELECT RAISE(ABORT,'immutable_ack'); END;
        """)
        for table in ["deliveries", "claims", "acknowledgments", "requests"]:
            c.execute(
                f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'immutable_source_record'); END"
            )


def append(config, feed, raw, replaces=()):
    if feed not in OWNERS[config["service"]] or len(raw) > LIMIT:
        raise ValueError("source_scope_or_size_denied")
    with sqlite(config["db"]) as c:
        c.execute("BEGIN IMMEDIATE")
        seq = c.execute("SELECT coalesce(max(seq),0)+1 FROM deliveries").fetchone()[0]
        for prior in replaces:
            row = c.execute("SELECT feed FROM deliveries WHERE seq=?", (prior,)).fetchone()
            if not row or row[0] != feed:
                raise ValueError("replacement_must_reference_same_source_feed")
        c.execute(
            "INSERT INTO deliveries VALUES(?,?,?,?,?)",
            (seq, feed, digest(raw), raw, json.dumps(list(replaces))),
        )
    return seq


def claim(
    config, feed, revision, complete=True, start="2026-09-01", through="2026-09-03", key=None
):
    if feed not in OWNERS[config["service"]] or type(complete) is not bool:
        raise ValueError("claim_scope_denied")
    body = {
        "id": key or feed,
        "revision": revision,
        "feed": feed,
        "start": start,
        "through": through,
        "complete": complete,
        "delivery_hashes": [],
    }
    with sqlite(config["db"]) as c:
        body["delivery_hashes"] = [
            r[0] for r in c.execute("SELECT sha FROM deliveries WHERE feed=? ORDER BY seq", (feed,))
        ]
        c.execute(
            "INSERT INTO claims VALUES(?,?,?)",
            (body["id"], revision, json.dumps(body, sort_keys=True)),
        )


def catalog(config):
    with sqlite(config["db"]) as c:
        c.execute("BEGIN")
        rows = [
            {
                "seq": r["seq"],
                "feed": r["feed"],
                "sha256": r["sha"],
                "bytes": len(r["raw"]),
                "replaces": json.loads(r["replaces_json"]),
            }
            for r in c.execute("SELECT * FROM deliveries ORDER BY seq")
        ]
        claims = [
            json.loads(r[0]) for r in c.execute("SELECT body FROM claims ORDER BY id,revision")
        ]
    return {"contract": 1, "service": config["service"], "deliveries": rows, "claims": claims}


def receipt(service, seq, sha):
    body = {"service": service, "seq": seq, "sha256": sha}
    return {**body, "ack_id": hash_value(body)}


def handler(config):
    class Source(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            response_headers(self, status, config["service"])
            self.send_header(
                "Content-Type",
                "application/octet-stream" if isinstance(body, bytes) else "application/json",
            )
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def auth(self, role):
            return hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + config[role + "_token"]
            )

        def do_GET(self):
            request_identity(self)
            path = urlparse(self.path).path
            if path in {"/health", "/livez"}:
                return self.reply(200, {"synthetic": True, "service": config["service"]})
            if path == "/readyz":
                try:
                    with sqlite(config["db"], readonly=True) as c:
                        ok = c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                        ok = (
                            ok
                            and c.execute("SELECT mode FROM faults WHERE id=1").fetchone()[0]
                            == "none"
                        )
                    return self.reply(
                        200 if ok else 503, {"status": "ready" if ok else "not_ready"}
                    )
                except Exception:
                    return self.reply(503, {"status": "not_ready"})
            if not self.auth("read"):
                return self.reply(403, {"error": "read_scope_denied"})
            with sqlite(config["db"]) as c:
                mode = c.execute("SELECT mode FROM faults WHERE id=1").fetchone()[0]
                if mode == "outage":
                    return self.reply(503, {"error": "controlled_source_outage"})
                if path == "/v1/catalog":
                    return self.reply(200, catalog(config))
                parts = path.strip("/").split("/")
                if (
                    len(parts) != 3
                    or parts[:2] not in [["v1", "delivery"], ["v1", "ack"]]
                    or not parts[2].isdigit()
                ):
                    return self.reply(404, {"error": "unknown_route"})
                seq = int(parts[2])
                if parts[1] == "ack":
                    if mode == "unknown_ack":
                        return self.reply(503, {"error": "ack_readback_unknown"})
                    row = c.execute(
                        "SELECT body FROM acknowledgments WHERE seq=?", (seq,)
                    ).fetchone()
                    return (
                        self.reply(200, json.loads(row[0]))
                        if row
                        else self.reply(
                            404, {"contract": 1, "absent_ack": seq, "service": config["service"]}
                        )
                    )
                row = c.execute("SELECT raw FROM deliveries WHERE seq=?", (seq,)).fetchone()
                if not row:
                    return self.reply(404, {"error": "unknown_delivery"})
                return self.reply(200, b"changed bytes" if mode == "corrupt_body" else row[0])

        def do_POST(self):
            request_identity(self)
            if self.path != "/v1/ack" or not self.auth("ack"):
                return self.reply(403, {"error": "ack_scope_denied"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 4096:
                    raise ValueError("bounded_ack_required")
                body = json.loads(self.rfile.read(length))
                if (
                    not isinstance(body, dict)
                    or set(body) != {"seq", "sha256"}
                    or type(body["seq"]) is not int
                ):
                    raise ValueError("invalid_ack")
                with sqlite(config["db"]) as c:
                    c.execute("BEGIN IMMEDIATE")
                    row = c.execute(
                        "SELECT sha FROM deliveries WHERE seq=?", (body["seq"],)
                    ).fetchone()
                    if not row or row[0] != body["sha256"]:
                        return self.reply(409, {"error": "exact_source_receipt_required"})
                    expected = receipt(config["service"], body["seq"], row[0])
                    mode = c.execute("SELECT mode FROM faults WHERE id=1").fetchone()[0]
                    if mode == "reject_ack":
                        c.execute(
                            "INSERT INTO requests(operation,seq,result,observed) VALUES('ack',?,'rejected',?)",
                            (body["seq"], now()),
                        )
                        c.commit()
                        return self.reply(503, {"error": "ack_not_committed"})
                    old = c.execute(
                        "SELECT body FROM acknowledgments WHERE seq=?", (body["seq"],)
                    ).fetchone()
                    c.execute(
                        "INSERT OR IGNORE INTO acknowledgments VALUES(?,?)",
                        (body["seq"], json.dumps(expected)),
                    )
                    lost = mode == "lost_ack" and not old
                    c.execute(
                        "INSERT INTO requests(operation,seq,result,observed) VALUES('ack',?,?,?)",
                        (
                            body["seq"],
                            "committed_ack_lost" if lost else "duplicate" if old else "committed",
                            now(),
                        ),
                    )
                return (
                    self.reply(503, {"error": "acknowledgment_lost"})
                    if lost
                    else self.reply(200, expected)
                )
            except (ValueError, KeyError, TypeError):
                return self.reply(400, {"error": "invalid_ack"})

    identifier(config["service"])
    return Source


def serve(config, host="127.0.0.1", port=0):
    return BoundedServer((host, port), handler(config))
