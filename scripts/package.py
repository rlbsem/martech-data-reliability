"""Create a byte-verified delivery ZIP only from a currently verified source tree."""

import argparse
import json
from zipfile import ZIP_DEFLATED, ZipFile

from marketing_reliability.contracts import digest
from repository import ROOT, files, fingerprint, inventory, links


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, required=True)
    args = parser.parse_args()
    verification = json.loads((ROOT / "docs/evidence/verification.json").read_text())
    assert verification["source_fingerprint"] == fingerprint(), (
        "run verification after source changes"
    )
    for name, checksum in verification["generated_evidence"].items():
        assert digest((ROOT / "docs/evidence" / name).read_bytes()) == checksum, (
            f"changed evidence: {name}"
        )
    links()
    inventory()
    from pathlib import Path

    output = Path(args.output).resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("write the ZIP outside the repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = files()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in payload:
            archive.write(path, ROOT.name + "/" + path.relative_to(ROOT).as_posix())
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == len(payload)
        for path in payload:
            assert (
                archive.read(ROOT.name + "/" + path.relative_to(ROOT).as_posix())
                == path.read_bytes()
            )
    checksum = digest(output.read_bytes())
    output.with_suffix(".zip.sha256").write_text(
        checksum + "  " + output.name + "\n", encoding="ascii", newline="\n"
    )
    print(
        json.dumps(
            {"zip": str(output), "files": len(payload), "sha256": checksum, "all_bytes_match": True}
        )
    )


if __name__ == "__main__":
    main()
