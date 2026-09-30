import json
from pathlib import Path

import pytest

from marketing_reliability.contracts import canonical
from marketing_reliability.warehouse import Warehouse

ROOT = Path(__file__).resolve().parents[1]


def delivery(source, rows, key="batch", coverage="2026-09-03", version=1):
    return canonical(
        {
            "source": source,
            "batch_id": key,
            "schema_version": version,
            "covered_through": coverage,
            "rows": rows,
        }
    ).encode()


def load(w, number):
    return w.ingest(next(ROOT.joinpath("fixtures").glob(f"{number:02d}-*.json")).read_bytes())


def fixture(number):
    return json.loads(next(ROOT.joinpath("fixtures").glob(f"{number:02d}-*.json")).read_bytes())


@pytest.fixture
def warehouse(tmp_path):
    with Warehouse(tmp_path / "state") as value:
        yield value


@pytest.fixture
def baseline(warehouse):
    for number in range(1, 5):
        load(warehouse, number)
    run = warehouse.plan("2026-09-04")
    warehouse.build(run)
    warehouse.publish(run)
    return warehouse
