import argparse
import json
from pathlib import Path

from .controller import Operations


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("operation", choices=["ingest", "build"])
    p.add_argument("--service", default="website")
    p.add_argument("--name", default="crash-rebuild")
    p.add_argument("--crash", required=True)
    a = p.parse_args()
    with Operations(json.loads(Path(a.config).read_bytes())) as ops:
        if a.operation == "ingest":
            ops.sync(a.service, crash=a.crash)
        else:
            found = ops.w.rows("SELECT run_id FROM ops_candidates WHERE name=?", [a.name])
            if not found:
                raise ValueError("unknown_persisted_rebuild")
            ops.w.build(found[0][0], crash=a.crash)


if __name__ == "__main__":
    main()
