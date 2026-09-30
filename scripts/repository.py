"""Delivery inventory and Markdown checks, shared by verification and packaging."""

import json
import re
from pathlib import Path
from urllib.parse import unquote

from marketing_reliability.contracts import canonical, digest

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "work", "build", "dist", "__pycache__", ".pytest_cache", ".ruff_cache"}


def files():
    def walk(folder):
        for entry in sorted(folder.iterdir()):
            if entry.name in EXCLUDED or entry.name.endswith(".egg-info"):
                continue
            if entry.is_dir():
                yield from walk(entry)
            else:
                yield entry

    return list(walk(ROOT))


def source_manifest():
    return {
        p.relative_to(ROOT).as_posix(): digest(p.read_bytes())
        for p in files()
        if not p.is_relative_to(ROOT / "docs/evidence")
    }


def fingerprint():
    return digest(canonical(source_manifest()).encode())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def links():
    checked = 0
    for path in files():
        if path.suffix != ".md":
            continue
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if re.match(r"https?://|mailto:", link):
                continue
            target, _, fragment = unquote(link).partition("#")
            dest = (path.parent / target).resolve() if target else path
            if not dest.is_relative_to(ROOT) or not dest.exists():
                raise AssertionError(f"broken Markdown target: {path.name}: {link}")
            if fragment and dest.suffix == ".md":
                headings = re.findall(r"^#+\s+(.+)$", dest.read_text(encoding="utf-8"), re.M)
                anchors = {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in headings}
                if fragment not in anchors:
                    raise AssertionError(f"broken Markdown anchor: {link}")
            checked += 1
    return checked


def inventory():
    evidence = ROOT / "docs/evidence"
    tree = evidence / "repository-tree.txt"
    manifest = evidence / "package-manifest.json"
    names = sorted(
        {p.relative_to(ROOT).as_posix() for p in files()}
        | {tree.relative_to(ROOT).as_posix(), manifest.relative_to(ROOT).as_posix()}
    )
    tree.write_text("\n".join(names) + "\n", encoding="utf-8", newline="\n")
    entries = {
        p.relative_to(ROOT).as_posix(): {
            "sha256": digest(p.read_bytes()),
            "bytes": p.stat().st_size,
        }
        for p in files()
        if p != manifest
    }
    save(
        manifest,
        {"format": 1, "excluded_self": "docs/evidence/package-manifest.json", "files": entries},
    )
    return entries
