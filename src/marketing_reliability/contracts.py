"""Closed delivery contracts. No coercion of identifiers, dates, money or booleans."""

import hashlib
import json
import re
from datetime import date
from pathlib import Path

SOURCES = ("campaigns", "paid_media", "web", "crm")
METRICS = ("cost_cents", "impressions", "clicks", "conversions", "revenue_cents")


class ContractError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ContractError(f"nonfinite JSON: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value):
        raise ContractError("identifier must be 1..80 ASCII letters, digits, _ or -")
    return value


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ContractError("date must be YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ContractError("invalid calendar date") from error
    return value


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 10**12:
        raise ContractError(f"integer required in [{minimum}, 10^12]")
    return value


def envelope(raw):
    try:
        value = strict_json(raw)
    except (ValueError, UnicodeError) as error:
        raise ContractError(str(error)) from error
    fields = {"source", "batch_id", "schema_version", "covered_through", "rows"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractError("delivery envelope fields do not match contract")
    identifier(value["batch_id"])
    if value["source"] not in SOURCES:
        raise ContractError("unknown source")
    supported = (1, 2) if value["source"] == "paid_media" else (1,)
    if type(value["schema_version"]) is not int or value["schema_version"] not in supported:
        raise ContractError("unsupported schema version; delivery requires upstream repair")
    day(value["covered_through"])
    if not isinstance(value["rows"], list) or len(value["rows"]) > 100000:
        raise ContractError("rows must be an array of at most 100000 elements")
    return value


def record(source, version, value):
    if not isinstance(value, dict):
        raise ContractError("row must be an object")
    base = {"id", "revision", "op"}
    if not base <= set(value):
        raise ContractError("missing identity/revision/operation")
    identifier(value["id"])
    integer(value["revision"], 1)
    if value["op"] not in ("upsert", "delete"):
        raise ContractError("unknown operation")
    extra = {
        "campaigns": {"name"},
        "paid_media": {"day", "campaign_id", "cost_cents", "impressions", "clicks"},
        "web": {"day", "campaign_id", "conversions"},
        "crm": {"day", "campaign_id", "revenue_cents"},
    }[source]
    if source == "paid_media" and version == 2:
        extra = extra | {"currency"}
    expected = base if value["op"] == "delete" else base | extra
    if set(value) != expected:
        raise ContractError("row fields do not match declared contract")
    result = dict(value)
    if value["op"] == "delete":
        return result
    if source == "campaigns":
        if not isinstance(value["name"], str) or not 1 <= len(value["name"].strip()) <= 120:
            raise ContractError("campaign name must contain 1..120 characters")
    else:
        day(value["day"])
        identifier(value["campaign_id"])
        for field in METRICS:
            if field in value:
                integer(value[field])
        if source == "web" and value["conversions"] not in (0, 1):
            raise ContractError("web row is one event, conversions must be 0 or 1")
        if source == "paid_media":
            if value["clicks"] > value["impressions"]:
                raise ContractError("clicks exceed impressions")
            if version == 2 and value["currency"] != "USD":
                raise ContractError("only USD is supported")
            result["currency"] = "USD"  # v1's documented unit, never inferred from values.
    return result


def implementation_hash():
    root = Path(__file__).parent
    files = sorted(p for p in root.rglob("*") if p.suffix in (".py", ".sql"))
    return digest(
        canonical({p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in files}).encode()
    )
