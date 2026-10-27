import argparse
import json
from pathlib import Path

from .view import verify_live


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(verify_live(json.loads(args.config.read_bytes())), indent=2))


if __name__ == "__main__":
    main()
