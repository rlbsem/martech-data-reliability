import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from marketing_reliability.contracts import day, digest, strict_json

from .common import LIMIT, OWNERS
from .source import receipt


class Unknown(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


class Client:
    def __init__(self, config):
        self.config = config
        p = urlparse(config["url"])
        if (
            p.scheme != "http"
            or p.hostname not in {"127.0.0.1", "localhost", *OWNERS}
            or p.username
            or p.password
            or p.path not in {"", "/"}
            or p.query
            or p.fragment
        ):
            raise ValueError("isolated_source_endpoint_required")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, path, body=None):
        token = self.config["read_token" if body is None else "ack_token"]
        req = Request(
            self.config["url"].rstrip("/") + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            response = self.opener.open(req, timeout=3)
        except HTTPError as e:
            response = e
        except (OSError, URLError) as e:
            raise Unknown("source_transport_unknown") from e
        with response:
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise Unknown("source_response_exceeds_limit")
            return response.code, raw

    def catalog(self):
        status, raw = self.request("/v1/catalog")
        if status != 200:
            raise Unknown("source_http_status_" + str(status))
        try:
            body = strict_json(raw)
            assert (
                status == 200
                and isinstance(body, dict)
                and set(body) == {"contract", "service", "deliveries", "claims"}
            )
            assert (
                type(body["contract"]) is int
                and body["contract"] == 1
                and body["service"] == self.config["service"]
            )
            assert isinstance(body["deliveries"], list) and len(body["deliveries"]) <= 1000
            for i, entry in enumerate(body["deliveries"], 1):
                assert set(entry) == {"seq", "feed", "sha256", "bytes", "replaces"}
                assert (
                    type(entry["seq"]) is int
                    and entry["seq"] == i
                    and entry["feed"] in OWNERS[body["service"]]
                )
                assert isinstance(entry["sha256"], str) and re.fullmatch(
                    r"[a-f0-9]{64}", entry["sha256"]
                )
                assert type(entry["bytes"]) is int and 0 < entry["bytes"] <= LIMIT
                assert isinstance(entry["replaces"], list) and all(
                    type(n) is int
                    and 1 <= n < i
                    and body["deliveries"][n - 1]["feed"] == entry["feed"]
                    for n in entry["replaces"]
                )
            assert isinstance(body["claims"], list) and len(body["claims"]) <= 1000
            keys = set()
            for claim in body["claims"]:
                assert set(claim) == {
                    "id",
                    "revision",
                    "feed",
                    "start",
                    "through",
                    "complete",
                    "delivery_hashes",
                }
                assert (
                    claim["feed"] in OWNERS[body["service"]]
                    and type(claim["revision"]) is int
                    and claim["revision"] > 0
                )
                assert isinstance(claim["id"], str) and type(claim["complete"]) is bool
                assert day(claim["start"]) <= day(claim["through"])
                assert isinstance(claim["delivery_hashes"], list) and all(
                    isinstance(h, str) and re.fullmatch(r"[a-f0-9]{64}", h)
                    for h in claim["delivery_hashes"]
                )
                key = (claim["id"], claim["revision"])
                assert key not in keys
                keys.add(key)
        except (ValueError, TypeError, KeyError, AssertionError):
            raise Unknown("catalog_contract_or_ownership_unknown") from None
        return body

    def fetch(self, entry):
        status, raw = self.request("/v1/delivery/" + str(entry["seq"]))
        if status != 200:
            raise Unknown("delivery_http_status_" + str(status))
        if status != 200 or len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
            raise Unknown("delivery_content_not_verified")
        return raw

    def read_ack(self, entry):
        status, raw = self.request("/v1/ack/" + str(entry["seq"]))
        try:
            body = strict_json(raw)
        except (ValueError, UnicodeError):
            raise Unknown("ack_readback_invalid") from None
        if status == 404 and body == {
            "contract": 1,
            "absent_ack": entry["seq"],
            "service": self.config["service"],
        }:
            return None
        if status != 200 or body != receipt(self.config["service"], entry["seq"], entry["sha256"]):
            raise Unknown("ack_readback_not_exact")
        return body
