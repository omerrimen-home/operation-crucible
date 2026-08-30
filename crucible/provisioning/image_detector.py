#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "ERROR: PyYAML is required.\n"
        "Install it with: python3 -m pip install PyYAML",
        file=sys.stderr,
    )
    sys.exit(1)


# operation-crucible/
# └── crucible/
#     └── provisioning/
#         └── image_detector.py
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG = REPO_ROOT / "config" / "images.yml"


@dataclass
class ImageRecord:
    image_id: str
    path: str
    filename: str
    size_bytes: int
    mtime_ns: int
    sha256: str
    family: str | None
    distribution: str | None
    version: str | None
    architecture: str | None
    installer: str | None
    flavor: str | None
    media_type: str | None
    volume_label: str | None
    osinfo_hint: str | None
    confidence_score: int
    matched_by: list[str]


@dataclass
class UnknownImage:
    path: str
    filename: str
    size_bytes: int
    volume_label: str | None
    osinfo_hint: str | None


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML structure in {path}")

    return data


def run_command(command: list[str], timeout: int = 15) -> str | None:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )

        if result.returncode != 0:
            return None

        output = result.stdout.strip()
        return output or None

    except (OSError, subprocess.TimeoutExpired):
        return None


def get_volume_label(path: Path) -> str | None:
    """
    Attempt to read an ISO9660/UDF volume label.

    First tries blkid, which is normally available on Ubuntu.
    Falls back to isoinfo if installed.
    """

    if shutil.which("blkid"):
        label = run_command(
            [
                "blkid",
                "-o",
                "value",
                "-s",
                "LABEL",
                str(path),
            ]
        )

        if label:
            return label.strip()

    if shutil.which("isoinfo"):
        output = run_command(
            [
                "isoinfo",
                "-d",
                "-i",
                str(path),
            ]
        )

        if output:
            for line in output.splitlines():
                if line.lower().startswith("volume id:"):
                    return line.split(":", 1)[1].strip()

    return None


def get_osinfo_hint(path: Path) -> str | None:
    """
    osinfo-detect is optional.

    Crucible does not depend on it, but if libosinfo happens to know
    the installation media, its output becomes an additional detection
    signal.
    """

    if not shutil.which("osinfo-detect"):
        return None

    return run_command(["osinfo-detect", str(path)])


def regex_matches(patterns: list[str], value: str | None) -> bool:
    if not value:
        return False

    for pattern in patterns:
        try:
            if re.search(pattern, value, flags=re.IGNORECASE):
                return True
        except re.error as exc:
            raise ValueError(
                f"Invalid regular expression '{pattern}': {exc}"
            ) from exc

    return False


def classify_image(
    iso_path: Path,
    image_definitions: dict[str, Any],
    volume_label: str | None,
    osinfo_hint: str | None,
) -> tuple[str | None, int, list[str], bool]:
    """
    Return:

        image_id
        score
        matched_by
        ambiguous

    Filename matches have the strongest weight because they are under
    the local operator's control.

    Volume label and libosinfo information provide additional evidence.
    """

    candidates: list[tuple[str, int, list[str]]] = []

    filename = iso_path.name

    for image_id, definition in image_definitions.items():
        match_rules = definition.get("match", {})

        score = 0
        matched_by: list[str] = []

        if regex_matches(match_rules.get("filename", []), filename):
            score += 100
            matched_by.append("filename")

        if regex_matches(
            match_rules.get("volume_label", []),
            volume_label,
        ):
            score += 40
            matched_by.append("volume-label")

        if regex_matches(
            match_rules.get("osinfo", []),
            osinfo_hint,
        ):
            score += 20
            matched_by.append("osinfo")

        if score > 0:
            candidates.append((image_id, score, matched_by))

    if not candidates:
        return None, 0, [], False

    candidates.sort(key=lambda item: item[1], reverse=True)

    highest_score = candidates[0][1]

    winners = [
        candidate
        for candidate in candidates
        if candidate[1] == highest_score
    ]

    if len(winners) > 1:
        return None, highest_score, [], True

    image_id, score, matched_by = winners[0]

    return image_id, score, matched_by, False


def determine_media_type(
    image_id: str,
    filename: str,
    definition: dict[str, Any],
) -> str | None:

    declared_media_type = (
        definition.get(
            "media_type"
        )
    )

    if declared_media_type:
        return str(
            declared_media_type
        ).strip().lower()

    lowered = filename.lower()

    if image_id == "kali-rolling":
        if "-installer-" in lowered:
            return "installer"

        if "-netinst-" in lowered:
            return "netinst"

        if "-live-" in lowered:
            return "live"

        return "unknown"

    flavor = definition.get(
        "flavor"
    )

    if flavor:
        return str(
            flavor
        ).strip().lower()

    return None


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def load_existing_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {}

    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if isinstance(data, dict):
            return data

    except (json.JSONDecodeError, OSError):
        pass

    return {}


def get_cached_hash(
    iso_path: Path,
    stat: Any,
    existing_cache: dict[str, Any],
) -> str | None:

    cached_images = existing_cache.get("files", {})

    cached = cached_images.get(str(iso_path.resolve()))

    if not cached:
        return None

    if cached.get("size_bytes") != stat.st_size:
        return None

    if cached.get("mtime_ns") != stat.st_mtime_ns:
        return None

    return cached.get("sha256")


def scan_images(
    config_path: Path,
    rehash: bool = False,
) -> tuple[dict[str, Any], bool]:

    config = load_yaml(config_path)

    paths_config = config.get("paths", {})
    image_definitions = config.get("images", {})

    iso_directory = REPO_ROOT / paths_config.get(
        "iso_directory",
        "images/iso",
    )

    cache_path = REPO_ROOT / paths_config.get(
        "cache_file",
        ".crucible/image-index.json",
    )

    if not iso_directory.exists():
        raise FileNotFoundError(
            f"ISO directory does not exist: {iso_directory}"
        )

    existing_cache = load_existing_cache(cache_path)

    iso_files = sorted(
        path
        for path in iso_directory.iterdir()
        if path.is_file() and path.suffix.lower() == ".iso"
    )

    recognized: dict[str, list[dict[str, Any]]] = {}
    unknown: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []

    file_cache: dict[str, Any] = {}

    for iso_path in iso_files:
        stat = iso_path.stat()

        volume_label = get_volume_label(iso_path)
        osinfo_hint = get_osinfo_hint(iso_path)

        image_id, score, matched_by, is_ambiguous = classify_image(
            iso_path,
            image_definitions,
            volume_label,
            osinfo_hint,
        )

        if is_ambiguous:
            ambiguous.append(
                {
                    "path": str(iso_path.resolve()),
                    "filename": iso_path.name,
                    "volume_label": volume_label,
                    "osinfo_hint": osinfo_hint,
                }
            )
            continue

        if image_id is None:
            unknown_record = UnknownImage(
                path=str(iso_path.resolve()),
                filename=iso_path.name,
                size_bytes=stat.st_size,
                volume_label=volume_label,
                osinfo_hint=osinfo_hint,
            )

            unknown.append(asdict(unknown_record))
            continue

        definition = image_definitions[image_id]

        sha256 = None

        if not rehash:
            sha256 = get_cached_hash(
                iso_path,
                stat,
                existing_cache,
            )

        if not sha256:
            print(f"[HASH] {iso_path.name}")
            sha256 = calculate_sha256(iso_path)

        media_type = determine_media_type(
            image_id,
            iso_path.name,
            definition,
        )

        record = ImageRecord(
            image_id=image_id,
            path=str(iso_path.resolve()),
            filename=iso_path.name,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            sha256=sha256,
            family=definition.get("family"),
            distribution=definition.get("distribution"),
            version=definition.get("version"),
            architecture=definition.get("architecture"),
            installer=definition.get("installer"),
            flavor=definition.get("flavor"),
            media_type=media_type,
            volume_label=volume_label,
            osinfo_hint=osinfo_hint,
            confidence_score=score,
            matched_by=matched_by,
        )

        serialized = asdict(record)

        recognized.setdefault(image_id, []).append(serialized)

        file_cache[str(iso_path.resolve())] = {
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256,
        }

    missing: list[str] = []

    for image_id, definition in image_definitions.items():
        if not definition.get("required", False):
            continue

        if image_id not in recognized:
            missing.append(image_id)

    duplicates = {
        image_id: records
        for image_id, records in recognized.items()
        if len(records) > 1
    }

    valid = (
        len(missing) == 0
        and len(duplicates) == 0
        and len(ambiguous) == 0
    )

    result = {
        "schema_version": 2,
        "valid": valid,
        "iso_directory": str(iso_directory.resolve()),
        "recognized": recognized,
        "missing": missing,
        "duplicates": duplicates,
        "unknown": unknown,
        "ambiguous": ambiguous,
        "files": file_cache,
    }

    cache_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(
            result,
            handle,
            indent=2,
            sort_keys=True,
        )

    return result, valid


def human_size(size: int) -> str:
    value = float(size)

    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"

        value /= 1024

    return f"{size} B"


def print_report(result: dict[str, Any]) -> None:
    print()
    print("Operation Crucible - Image Discovery")
    print("=" * 50)
    print()

    recognized = result["recognized"]

    for image_id in sorted(recognized):
        records = recognized[image_id]

        if len(records) == 1:
            record = records[0]

            print(f"[FOUND] {image_id}")
            print(f"        File:   {record['filename']}")
            print(
                f"        Size:   "
                f"{human_size(record['size_bytes'])}"
            )
            print(
                f"        Match:  "
                f"{', '.join(record['matched_by'])}"
            )

            if record.get("media_type"):
                print(
                    f"        Media:  "
                    f"{record['media_type']}"
                )

            if record.get("volume_label"):
                print(
                    f"        Label:  "
                    f"{record['volume_label']}"
                )

            print(
                f"        SHA256: "
                f"{record['sha256']}"
            )
            print()

        else:
            print(f"[DUPLICATE] {image_id}")

            for record in records:
                print(f"            {record['filename']}")

            print()

    for image_id in result["missing"]:
        print(f"[MISSING] {image_id}")

    if result["missing"]:
        print()

    for record in result["unknown"]:
        print(f"[UNKNOWN] {record['filename']}")

        if record.get("volume_label"):
            print(f"          Label: {record['volume_label']}")

    if result["unknown"]:
        print()

    for record in result["ambiguous"]:
        print(f"[AMBIGUOUS] {record['filename']}")

    if result["ambiguous"]:
        print()

    print("-" * 50)

    unique_recognized = sum(
        1
        for records in recognized.values()
        if len(records) == 1
    )

    print(f"Recognized: {unique_recognized}")
    print(f"Missing:    {len(result['missing'])}")
    print(f"Unknown:    {len(result['unknown'])}")
    print(f"Ambiguous:  {len(result['ambiguous'])}")
    print(f"Duplicates: {len(result['duplicates'])}")

    if result["valid"]:
        print()
        print("[PASS] Image inventory is valid.")
    else:
        print()
        print("[FAIL] Image inventory requires attention.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Discover and identify operating-system ISO images "
            "available to Operation Crucible."
        )
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to images.yml",
    )

    parser.add_argument(
        "--rehash",
        action="store_true",
        help="Ignore cached SHA-256 values and hash all ISOs again.",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the resulting inventory as JSON.",
    )

    args = parser.parse_args()

    try:
        result, valid = scan_images(
            args.config.resolve(),
            rehash=args.rehash,
        )

    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)

    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
