import argparse
import json
from pathlib import Path

from .common import OWNERS
from .demo import execute
from .runtime import configure, private
from .view import verify_live


def main():
    p = argparse.ArgumentParser()
    p.add_argument("step", choices=["initialize", "demo"])
    args = p.parse_args()
    if args.step == "initialize":
        configure(Path("/control"), {s: f"http://{s}:8340" for s in OWNERS}, docker=True)
        original, target = Path("/control/console.json"), Path("/console-config/console.json")
        if original.exists():
            private(target, json.loads(original.read_bytes()))
            original.unlink()
        if not target.exists():
            raise ValueError("separate_read_only_configuration_missing")
        return
    controller = Path("/control/controller.json")
    config = json.loads(controller.read_bytes())
    sources = {s: json.loads((Path("/sources") / s / "source.json").read_bytes()) for s in OWNERS}
    report = execute(config, sources, controller)
    readonly = {
        "state": config["state"],
        "sources": {
            s: {k: v for k, v in c.items() if k != "ack_token"}
            for s, c in config["sources"].items()
        },
    }
    print(json.dumps({"scenario_assertions": len(report["checks"]), **verify_live(readonly)}))


if __name__ == "__main__":
    main()
