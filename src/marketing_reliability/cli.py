import argparse
import json
import sys
from pathlib import Path

from .warehouse import Warehouse


def main():
    parser = argparse.ArgumentParser(description="Synthetic marketing warehouse pipeline")
    parser.add_argument("--state", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest")
    ingest.add_argument("file", type=Path)
    ingest.add_argument(
        "--crash",
        choices=["after_landing", "during_ingest", "before_ingest_commit", "after_ingest_commit"],
    )
    plan = commands.add_parser("plan")
    plan.add_argument("--as-of", required=True)
    plan.add_argument("--date", action="append", dest="dates")
    plan.add_argument("--full", action="store_true")
    for name in ("build", "publish", "lineage"):
        command = commands.add_parser(name)
        command.add_argument("run_id", type=int)
        if name != "lineage":
            command.add_argument(
                "--crash",
                choices=["during_build", "after_build_commit"]
                if name == "build"
                else ["before_publish_commit", "after_publish_commit"],
            )
    commands.add_parser("report")
    args = parser.parse_args()
    try:
        result = execute(args)
    except ValueError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        raise SystemExit(2) from error
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if isinstance(result, dict) and (
        result.get("status") == "rejected" or (result.get("evidence") or {}).get("blockers")
    ):
        raise SystemExit(2)


def execute(args):
    with Warehouse(args.state) as warehouse:
        match args.command:
            case "ingest":
                result = warehouse.ingest(args.file.read_bytes(), args.crash)
            case "plan":
                result = {"run_id": warehouse.plan(args.as_of, args.dates, args.full)}
            case "build" | "publish":
                result = getattr(warehouse, args.command)(args.run_id, args.crash)
            case "lineage":
                result = warehouse.lineage(args.run_id)
            case "report":
                result = warehouse.reconcile()
    return result


if __name__ == "__main__":
    main()
