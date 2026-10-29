"""Quiescent publication backup; restoration never authorizes source acknowledgments."""

import argparse
import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from marketing_reliability.contracts import digest

from .common import now, save, single_writer
from .operational import readiness


def inventory(root):
    result = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError("symlink_not_permitted")
        if p.is_file() and p != root / "manifest.json":
            result[p.relative_to(root).as_posix()] = digest(p.read_bytes())
    return result


def validate(archive):
    archive = Path(archive).resolve()
    manifest = json.loads((archive / "manifest.json").read_bytes())
    if manifest.get("contract") != 1 or not manifest.get("files"):
        raise ValueError("invalid_backup_manifest")
    if inventory(archive) != manifest["files"]:
        raise ValueError("backup_content_changed")
    for name in manifest["files"]:
        path = (archive / name).resolve()
        if not path.is_relative_to(archive / "state"):
            raise ValueError("backup_path_outside_state")
    return manifest


def _private_dir(path):
    path.mkdir(mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)


def backup(config, destination):
    from .runtime import source_hash

    root, destination = Path(config["state"]).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(root):
        raise ValueError("fresh_backup_outside_state_required")
    temp = destination.with_name(destination.name + ".partial-" + uuid.uuid4().hex)
    temp.parent.mkdir(parents=True, exist_ok=True)
    _private_dir(temp)
    try:
        with single_writer(root / "controller.lock"):
            before = readiness(config)
            if before["status"] != "ready":
                raise ValueError("backup_requires_verified_quiescent_publication")
            for p in root.rglob("*"):
                if p.is_symlink():
                    raise ValueError("symlink_not_permitted")
                if p.is_file() and p.suffix == ".wal" and p.stat().st_size:
                    raise ValueError("warehouse_checkpoint_required")
            target = temp / "state"
            shutil.copytree(
                root,
                target,
                ignore=shutil.ignore_patterns(
                    "controller.lock",
                    "operations.sqlite",
                    "operations.sqlite-wal",
                    "operations.sqlite-shm",
                ),
            )
            with closing(
                sqlite3.connect(root.as_uri() + "/operations.sqlite?mode=ro", uri=True)
            ) as src:
                with closing(sqlite3.connect(target / "operations.sqlite")) as dst:
                    src.backup(dst)
            restored = readiness({**config, "state": str(target)})
            after = readiness(config)
            keys = ["status", "active_run", "source_inventory_sha256", "totals"]
            if any(before.get(k) != x.get(k) for k in keys for x in [after, restored]):
                raise ValueError("backup_inventory_changed_or_copy_not_verified")
            save(
                temp / "manifest.json",
                {
                    "contract": 1,
                    "created_at": now(),
                    "scope": "publication_state_only",
                    "implementation_sha256": source_hash(),
                    "source_inventory_sha256": before["source_inventory_sha256"],
                    "active_run": before["active_run"],
                    "totals": before["totals"],
                    "files": inventory(temp),
                },
            )
            validate(temp)
            temp.rename(destination)
    except BaseException:
        # Retain failed candidate privately for diagnosis. Never present it as complete.
        raise
    return {
        "status": "passed",
        "files": len(validate(destination)["files"]),
        "scope": "publication_state_only",
        "credentials_included": False,
    }


def restore(config, archive, target):
    from .runtime import source_hash

    manifest = validate(archive)
    if manifest["implementation_sha256"] != source_hash():
        raise ValueError("restore_requires_matching_implementation")
    target = Path(target).resolve()
    if target.exists() or target.is_relative_to(Path(archive).resolve()):
        raise ValueError("restore_requires_new_empty_destination")
    target.parent.mkdir(parents=True, exist_ok=True)
    _private_dir(target)
    try:
        shutil.copytree(Path(archive) / "state", target, dirs_exist_ok=True)
        result = readiness({**config, "state": str(target)})
        if (
            result["status"] != "ready"
            or result["source_inventory_sha256"] != manifest["source_inventory_sha256"]
            or result["totals"] != manifest["totals"]
            or result["active_run"] != manifest["active_run"]
        ):
            raise ValueError("restore_not_ready_against_independent_sources")
        return {
            "status": "passed",
            "active_run": result["active_run"],
            "totals": result["totals"],
            "source_writes": 0,
            "automatic_controller_resume": False,
        }
    except BaseException:
        # A failed isolated copy is retained; no active pointer or configuration is changed.
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["backup", "restore"])
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--target", type=Path)
    a = p.parse_args()
    config = json.loads(a.config.read_bytes())
    if a.mode == "restore" and a.target is None:
        p.error("restore requires --target")
    result = (
        backup(config, a.archive) if a.mode == "backup" else restore(config, a.archive, a.target)
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
