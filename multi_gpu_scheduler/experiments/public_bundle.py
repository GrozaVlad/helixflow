"""Strict, standard-library-only validation of a public workload projection.

Also distributed as verify_public_bundle.py inside the public input archive.
The original frozen.json remains unchanged; only source-cache/*.json may be omitted.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath

MANIFEST = "public-release.json"
DOCUMENTATION = {"README.md", "DATA_NOTICE.md", "verify_public_bundle.py"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_path(root, relative):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or str(parts) != relative:
        raise ValueError(f"unsafe public bundle path: {relative}")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"unsafe public bundle path: {relative}")
    return path


def cache_record(relative):
    parts = PurePosixPath(relative).parts
    return len(parts) == 2 and parts[0] == "source-cache" and parts[1].endswith(".json")


def validate_public_inventory(root):
    """Return explicitly omitted cache entries, or fail on any inconsistent payload."""
    root = Path(root)
    release = json.loads((root / MANIFEST).read_text())
    if release.get("schema_version") != "1.0" or release.get("kind") != "helixflow-public-workload":
        raise ValueError("unsupported public bundle manifest")
    if digest(root / "frozen.json") != release.get("original_frozen_sha256"):
        raise ValueError("original frozen fingerprint changed")
    frozen = json.loads((root / "frozen.json").read_text())["sha256"]
    omitted = {name: checksum for name, checksum in frozen.items() if cache_record(name)}
    if release.get("omitted_source_cache") != omitted:
        raise ValueError("public bundle omissions must match only original source-cache records")
    inventory = release["files"]
    expected_names = (set(frozen) - set(omitted)) | {"frozen.json"} | DOCUMENTATION
    if set(inventory) != expected_names:
        raise ValueError("public bundle inventory missing required files or contains extra files")
    actual_names = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("public bundle must not contain symlinks")
        if path.is_file():
            actual_names.add(path.relative_to(root).as_posix())
    if actual_names != expected_names | {MANIFEST}:
        raise ValueError("public bundle payload missing files or contains unexpected files")
    for relative, entry in inventory.items():
        path = checked_path(root, relative)
        checksum = digest(path)
        if checksum != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise ValueError(f"public bundle asset changed: {relative}")
        if relative in frozen and checksum != frozen[relative]:
            raise ValueError(f"original benchmark asset changed: {relative}")
    return omitted


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    omitted = validate_public_inventory(args.root)
    release = json.loads((args.root / MANIFEST).read_text())
    print(json.dumps({"status": "PASSED", "kind": release["kind"],
                      "verified_files": len(release["files"]),
                      "omitted_source_cache_files": len(omitted),
                      "original_frozen_sha256": release["original_frozen_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
