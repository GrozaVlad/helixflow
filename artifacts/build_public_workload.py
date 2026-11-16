"""Package the frozen workload without mixed-provider cached source metadata."""
import argparse
import gzip
import importlib.util
import json
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
WORKLOAD = "public-v1-heme-ccd"
VALIDATOR = ROOT.parent / "multi_gpu_scheduler/experiments/public_bundle.py"
SPEC = importlib.util.spec_from_file_location("public_validator", VALIDATOR)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)


def build(source, output):
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{WORKLOAD}-public.tar.gz"
    if archive.exists():
        raise FileExistsError(f"Refusing to overwrite existing release: {archive}")
    original_manifest = ROOT / "workloads" / WORKLOAD / "frozen.json"
    original_bytes = original_manifest.read_bytes()
    frozen = json.loads(original_bytes)["sha256"]
    source_checksum = V.digest(source)
    with tempfile.TemporaryDirectory(prefix="helixflow-public-input-") as temporary:
        package = Path(temporary) / WORKLOAD
        package.mkdir()
        seen, verified = set(), set()
        with tarfile.open(source, "r|gz") as tar:
            for member in tar:
                parts = PurePosixPath(member.name)
                if parts.is_absolute() or ".." in parts.parts or parts.parts[0] != WORKLOAD:
                    raise ValueError("Unsafe source archive member")
                if member.name in seen:
                    raise ValueError("Duplicate source archive member")
                seen.add(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError("Source archive contains links or special files")
                relative = PurePosixPath(*parts.parts[1:]).as_posix()
                data = tar.extractfile(member).read()
                if relative == "frozen.json":
                    if data != original_bytes:
                        raise ValueError("Source frozen manifest differs from original checked-in copy")
                elif relative in frozen:
                    import hashlib

                    if hashlib.sha256(data).hexdigest() != frozen[relative]:
                        raise ValueError(f"Original source changed: {relative}")
                    verified.add(relative)
                elif relative == "README.md":
                    continue  # Replace packaging documentation, not scientific records.
                else:
                    raise ValueError(f"Unexpected source file: {relative}")
                if V.cache_record(relative):
                    continue
                destination = V.checked_path(package, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        if verified != set(frozen):
            raise ValueError("Full source archive is missing original frozen files")
        for name in ("README.md", "DATA_NOTICE.md"):
            shutil.copyfile(ROOT / "workloads" / WORKLOAD / name, package / name)
        shutil.copyfile(VALIDATOR, package / "verify_public_bundle.py")
        omitted = {name: checksum for name, checksum in frozen.items() if V.cache_record(name)}
        inventory = {
            p.relative_to(package).as_posix(): {"bytes": p.stat().st_size, "sha256": V.digest(p)}
            for p in sorted(package.rglob("*")) if p.is_file()
        }
        manifest = {
            "schema_version": "1.0", "kind": "helixflow-public-workload",
            "original_frozen_sha256": V.digest(original_manifest),
            "source_archive_sha256": source_checksum,
            "original_frozen_files_verified_during_packaging": len(verified),
            "omission_reason": "Mixed-provider source API cache is not required for inference; redistribution not established for all annotations.",
            "retained_scientific_files_modified": False,
            "data_notice": "DATA_NOTICE.md", "review_date": "2026-11-16",
            "omitted_source_cache": omitted, "files": inventory,
        }
        (package / V.MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
        V.validate_public_inventory(package)

        def normalize(info):
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            info.mode = 0o755 if info.isdir() else 0o644
            return info

        staged = Path(temporary) / archive.name
        with (
            staged.open("wb") as stream,
            gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as zipped,
            tarfile.open(fileobj=zipped, mode="w") as tar,
        ):
            tar.add(package, arcname=WORKLOAD, filter=normalize)
        # Independently read back compressed payload; never trust archive links.
        with tarfile.open(staged, "r:gz") as tar:
            files = set()
            for member in tar:
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError("Non-file release member")
                relative = str(PurePosixPath(member.name).relative_to(WORKLOAD))
                if relative in files or tar.extractfile(member).read() != (package / relative).read_bytes():
                    raise ValueError("Archive read-back mismatch")
                files.add(relative)
            if files != set(inventory) | {V.MANIFEST}:
                raise ValueError("Archive inventory mismatch")
        shutil.copyfile(staged, archive)
    # Only intended public attachments; never include the full private input archive.
    public_names = [archive.name, "helixflow-curated-evidence.tar.gz"]
    (output / "SHA256SUMS").write_text("".join(
        f"{V.digest(output / name)}  {name}\n"
        for name in sorted(public_names) if (output / name).is_file()
    ))
    result = {"archive": archive.name, "bytes": archive.stat().st_size,
              "sha256": V.digest(archive), "original_frozen_sha256": V.digest(original_manifest),
              "source_archive_sha256": source_checksum,
              "retained_original_files": len(frozen) - len(omitted),
              "omitted_source_cache_files": len(omitted), "verified_payload_files": len(inventory),
              "original_frozen_files_verified": len(verified), "status": "PASSED"}
    (output / "public-workload-validation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Complete original workload tar.gz")
    parser.add_argument("--output", type=Path, default=ROOT / "release-assets")
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), indent=2))
