import json

import pytest

from conftest import delivery, fixture
from marketing_reliability.contracts import ContractError, envelope, record


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("revision", 0),
        ("revision", 1.0),
        ("id", "../escape"),
        ("day", "2026-02-30"),
        ("day", "2026-9-01"),
        ("conversions", "1"),
        ("conversions", True),
        ("conversions", -1),
        ("conversions", 2),
        ("campaign_id", None),
        ("op", "append"),
    ],
)
def test_invalid_web_fields_are_not_coerced(field, value):
    row = {**fixture(3)["rows"][0], field: value}
    with pytest.raises(ContractError):
        record("web", 1, row)


@pytest.mark.parametrize("raw", [b"null", b"[]", b"{", b'{"a":1,"a":2}', b'{"a": NaN}', b"\xff"])
def test_bad_envelope_bytes_are_retained_and_rejected(warehouse, raw):
    result = warehouse.ingest(raw)
    assert result["status"] == "rejected"
    assert (warehouse.landing / f"{result['hash']}.json").read_bytes() == raw
    assert warehouse.ingest(raw)["replayed"]
    assert not warehouse.rows("SELECT * FROM coverage")


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 7),
        ("source", "unknown"),
        ("covered_through", "yesterday"),
        ("rows", {}),
        ("batch_id", "a/b"),
    ],
)
def test_delivery_contract(field, value):
    item = {**fixture(2), field: value}
    with pytest.raises(ContractError):
        envelope(json.dumps(item).encode())


def test_explicit_additive_schema_upgrade_has_same_meaning():
    value = fixture(2)["rows"][0]
    assert record("paid_media", 1, value) == record("paid_media", 2, {**value, "currency": "USD"})
    with pytest.raises(ContractError):
        record("paid_media", 1, {**value, "currency": "USD"})
    with pytest.raises(ContractError):
        record("paid_media", 2, {**value, "currency": "EUR"})


def test_future_row_quarantined_and_unknown_fields_not_dropped(warehouse):
    rows = [
        {**fixture(3)["rows"][0], "day": "2026-09-04"},
        {**fixture(3)["rows"][0], "secret": "x"},
    ]
    warehouse.ingest(delivery("web", rows))
    assert warehouse.reconcile()["row_dispositions"] == {"quarantined": 2}


@pytest.mark.parametrize(
    "change",
    [{"cost_cents": -1}, {"clicks": 1001}, {"impressions": 10**12 + 1}, {"cost_cents": 0.5}],
)
def test_money_and_counter_bounds(change):
    with pytest.raises(ContractError):
        record("paid_media", 1, {**fixture(2)["rows"][0], **change})
