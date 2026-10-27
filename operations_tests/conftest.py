import json
import time
from urllib.request import urlopen

import pytest

from reliability_ops.common import OWNERS
from reliability_ops.controller import Operations
from reliability_ops.runtime import LocalRuntime, free_port
from reliability_ops.scenario import raw_fixture
from reliability_ops.source import append, claim


@pytest.fixture
def runtime(tmp_path):
    with LocalRuntime(tmp_path / "runtime") as r:
        yield r


@pytest.fixture
def baseline(runtime):
    for service, numbers in {"advertising": [1, 2], "website": [3], "crm": [4]}.items():
        for number in numbers:
            raw = raw_fixture(number)
            append(runtime.source_configs[service], json.loads(raw)["source"], raw)
        for feed in OWNERS[service]:
            claim(runtime.source_configs[service], feed, 1)
    with Operations(runtime.config) as ops:
        for service in OWNERS:
            ops.sync(service)
        runtime.baseline = ops.candidate("baseline")
        ops.publish(runtime.baseline)
    return runtime


def console(runtime):
    port = free_port()
    runtime.spawn("console", runtime.root / "console.json", port)
    url = f"http://127.0.0.1:{port}/"
    for _ in range(50):
        try:
            urlopen(url + "health", timeout=2).close()
            return url
        except OSError:
            time.sleep(0.1)
    raise AssertionError("console_not_ready")
