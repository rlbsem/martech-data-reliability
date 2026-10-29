import base64
import json
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from marketing_reliability.contracts import digest

from .client import Client, Unknown
from .common import sqlite
from .view import state
from .operational import BoundedServer, readiness, request_identity, response_headers


def handler(config):
    class Console(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, body, content_type="application/json"):
            raw = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
            self.send_response(status)
            response_headers(self, status, "console")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            request_identity(self)
            self.reply(405, {"error": "read_only_operator_console"})

        do_PATCH = do_DELETE = do_PUT = do_POST

        def do_GET(self):
            request_identity(self)
            if urlparse("http://" + self.headers.get("Host", "")).hostname not in {
                "127.0.0.1",
                "localhost",
                "console",
            }:
                return self.reply(403, {"error": "local_host_required"})
            if self.headers.get("Origin") and urlparse(self.headers["Origin"]).hostname not in {
                "127.0.0.1",
                "localhost",
            }:
                return self.reply(403, {"error": "cross_origin_denied"})
            parsed = urlparse(self.path)
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if parsed.path in assets:
                file, mime = assets[parsed.path]
                return self.reply(200, (Path(__file__).parent / "web" / file).read_bytes(), mime)
            try:
                if parsed.path in {"/health", "/livez"}:
                    return self.reply(200, {"synthetic": True, "read_only": True})
                if parsed.path in {"/readyz", "/api/operations"}:
                    report = readiness(config)
                    return self.reply(200 if report["status"] == "ready" else 503, report)
                if parsed.path == "/api/state":
                    return self.reply(200, state(config))
                q = parse_qs(parsed.query)
                if parsed.path == "/api/ack":
                    if (
                        set(q) != {"service", "seq"}
                        or any(len(v) != 1 for v in q.values())
                        or q["service"][0] not in config["sources"]
                        or not q["seq"][0].isdigit()
                    ):
                        return self.reply(400, {"error": "invalid_receipt_reference"})
                    service, seq = q["service"][0], int(q["seq"][0])
                    with sqlite(Path(config["state"]) / "operations.sqlite", readonly=True) as c:
                        row = c.execute(
                            "SELECT metadata FROM deliveries WHERE service=? AND seq=?",
                            (service, seq),
                        ).fetchone()
                    if not row:
                        return self.reply(404, {"error": "unknown_observed_delivery"})
                    return self.reply(
                        200,
                        {
                            "independent_source_receipt": Client(
                                config["sources"][service]
                            ).read_ack(json.loads(row[0])),
                            "checkpoint_changed": False,
                        },
                    )
                if parsed.path == "/api/raw":
                    sha = q.get("sha", [""])[0]
                    if not re.fullmatch(r"[a-f0-9]{64}", sha):
                        return self.reply(400, {"error": "invalid_source_hash"})
                    path = Path(config["state"]) / "remote-landing" / (sha + ".bin")
                    if not path.exists():
                        return self.reply(404, {"error": "unknown_raw_delivery"})
                    raw = path.read_bytes()
                    if digest(raw) != sha:
                        raise ValueError("retained_input_changed")
                    return self.reply(
                        200,
                        {
                            "sha256": sha,
                            "bytes": len(raw),
                            "utf8_display": raw.decode("utf-8", errors="replace"),
                            "exact_base64": base64.b64encode(raw).decode(),
                        },
                    )
                return self.reply(404, {"error": "unknown_route"})
            except Unknown:
                return self.reply(503, {"error": "source_readback_unknown"})
            except Exception:
                return self.reply(503, {"error": "warehouse_busy_or_evidence_unverified"})

    return Console


def serve(config, host="127.0.0.1", port=0):
    return BoundedServer((host, port), handler(config))
