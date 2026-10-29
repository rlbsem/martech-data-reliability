import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from .client import Client
from .common import OWNERS, hash_value, save
from marketing_reliability.contracts import digest
from .source import initialize


def source_hash():
    root = Path(__file__).parents[1]
    entries = {
        p.relative_to(root).as_posix(): digest(p.read_bytes())
        for folder in [root / "reliability_ops", root / "marketing_reliability"]
        for p in sorted(folder.rglob("*"))
        if p.suffix in {".py", ".sql", ".html", ".css", ".js"}
    }
    entries.update(
        {
            "fixtures/" + p.name: digest(p.read_bytes())
            for p in sorted((Path.cwd() / "fixtures").glob("*.json"))
        }
    )
    if not any(k.startswith("fixtures/") for k in entries):
        raise ValueError("run_the_fixture_demo_from_the_repository_root")
    return hash_value(entries)


def private(path, body):
    save(path, body)
    if os.name != "nt":
        Path(path).chmod(0o600)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def configure(root, urls=None, docker=False):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "setup.json"
    if marker.exists():
        if json.loads(marker.read_bytes())["source_hash"] != source_hash():
            raise ValueError("code_changed_requires_explicit_fresh_demo")
        return json.loads((root / "controller.json").read_bytes())
    configs, sources = {}, {}
    reserved_ports = set()
    for service in OWNERS:
        folder = Path("/sources") / service if docker else root / "sources" / service
        folder.mkdir(parents=True, exist_ok=True)
        config = {
            "service": service,
            "db": str(folder / "source.sqlite"),
            "read_token": secrets.token_urlsafe(32),
            "ack_token": secrets.token_urlsafe(32),
        }
        initialize(config["db"])
        private(folder / "source.json", config)
        configs[service] = config
        port = free_port() if not urls else None
        while port in reserved_ports:
            port = free_port()
        reserved_ports.add(port)
        sources[service] = {
            "service": service,
            "url": urls[service] if urls else f"http://127.0.0.1:{port}",
            "read_token": config["read_token"],
            "ack_token": config["ack_token"],
        }
    state = "/state" if docker else str(root / "state")
    controller = {"state": state, "sources": sources}
    console = {
        "state": state,
        "sources": {
            s: {k: v for k, v in c.items() if k != "ack_token"} for s, c in sources.items()
        },
    }
    private(root / "controller.json", controller)
    private(root / "console.json", console)
    private(marker, {"source_hash": source_hash()})
    return controller


class LocalRuntime:
    def __init__(self, folder):
        self.root = Path(folder).resolve()
        self.children = []

    def __enter__(self):
        if self.root.exists():
            raise ValueError("fresh_local_workspace_required")
        self.config = configure(self.root)
        self.source_configs = {
            s: json.loads((self.root / "sources" / s / "source.json").read_bytes()) for s in OWNERS
        }
        try:
            for s, c in self.config["sources"].items():
                self.spawn(
                    "source",
                    self.root / "sources" / s / "source.json",
                    int(c["url"].rsplit(":", 1)[1]),
                )
                for _ in range(100):
                    try:
                        Client(c).catalog()
                        break
                    except Exception:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("source_not_ready")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def spawn(self, mode, config, port):
        # A same-port restart must retain earlier operational observations.
        f = (self.root / (mode + str(port) + ".log")).open("a", encoding="utf-8")
        p = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "reliability_ops.service",
                mode,
                "--config",
                str(config),
                "--port",
                str(port),
            ],
            stdout=f,
            stderr=subprocess.STDOUT,
        )
        self.children.append((p, f))
        return p

    def __exit__(self, *_):
        for child, f in reversed(self.children):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            f.close()
