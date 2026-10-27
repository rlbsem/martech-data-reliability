import argparse
import json
import time
from pathlib import Path

from .runtime import LocalRuntime, source_hash
from .scenario import run
from .view import verify_live


def execute(config, sources, controller_file):
    path = Path(config["state"]) / "acceptance.json"
    if path.exists():
        report = json.loads(path.read_bytes())
        if report["source_hash"] != source_hash():
            raise ValueError("changed_code_requires_explicit_fresh_demo")
        return report
    return run(config, sources, controller_file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8602)
    args = parser.parse_args()
    with LocalRuntime(args.workspace) as runtime:
        report = execute(runtime.config, runtime.source_configs, runtime.root / "controller.json")
        console = json.loads((runtime.root / "console.json").read_bytes())
        print(
            json.dumps({"scenario_assertions": len(report["checks"]), **verify_live(console)}),
            flush=True,
        )
        if args.serve:
            runtime.spawn("console", runtime.root / "console.json", args.port)
            print(f"Read-only console: http://127.0.0.1:{args.port}/", flush=True)
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
