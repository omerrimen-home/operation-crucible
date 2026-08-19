from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from crucible.hypervisors.virtualbox import VirtualBoxProvider
from crucible.provisioning.image_detector import load_yaml, scan_images


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MANIFEST = (
    REPO_ROOT
    / "manifests"
    / "machines"
    / "ubuntu-server.yml"
)

IMAGE_CONFIG = REPO_ROOT / "config" / "images.yml"
PROFILE_DIR = REPO_ROOT / "profiles" / "os"


class CrucibleError(RuntimeError):
    """Expected Operation Crucible orchestration error."""


def _repo_path(path: Path) -> Path:
    """Treat relative paths as relative to the repository root."""
    if path.is_absolute():
        return path

    return REPO_ROOT / path


def load_machine_manifest(path: Path) -> dict[str, Any]:
    """Load and minimally validate a machine manifest."""
    manifest = load_yaml(path)

    for key in ("name", "profile", "image_id"):
        if not manifest.get(key):
            raise CrucibleError(
                f"Manifest is missing required field: {key}"
            )

    return manifest


def load_os_profile(profile_name: str) -> dict[str, Any]:
    """Load an OS profile from profiles/os/."""
    profile_path = PROFILE_DIR / f"{profile_name}.yml"

    if not profile_path.is_file():
        raise CrucibleError(
            f"OS profile not found: {profile_path}"
        )

    return load_yaml(profile_path)


def resolve_iso(image_id: str) -> Path:
    """
    Ask the existing image detector to locate the ISO belonging
    to the requested logical image ID.
    """
    scan, _ = scan_images(IMAGE_CONFIG)

    records = (
        scan
        .get("recognized", {})
        .get(image_id, [])
    )

    if not records:
        raise CrucibleError(
            f"No ISO recognized for image_id '{image_id}'. "
            "Run: "
            "python3 -m crucible.provisioning.image_detector --json"
        )

    if len(records) > 1:
        paths = ", ".join(
            record["path"]
            for record in records
        )

        raise CrucibleError(
            f"Multiple ISOs matched image_id "
            f"'{image_id}': {paths}"
        )

    iso_path = Path(records[0]["path"])

    if not iso_path.is_file():
        raise CrucibleError(
            f"Resolved ISO does not exist: {iso_path}"
        )

    return iso_path


def create_machine(
    manifest_path: Path,
    *,
    verbose: bool = False,
) -> None:
    """Create one VM from a Crucible machine manifest."""

    manifest = load_machine_manifest(manifest_path)

    name = str(manifest["name"])
    profile_name = str(manifest["profile"])
    image_id = str(manifest["image_id"])

    resources = manifest.get("resources", {})
    network = manifest.get("network", {})
    start = manifest.get("start", {})

    # ---------------------------------------------------------
    # 1. Load OS profile
    # ---------------------------------------------------------

    print(f"[1/5] Loading OS profile: {profile_name}")

    profile = load_os_profile(profile_name)

    # ---------------------------------------------------------
    # 2. Find installation ISO
    # ---------------------------------------------------------

    print(f"[2/5] Resolving installation ISO: {image_id}")

    iso_path = resolve_iso(image_id)

    print(f"      -> {iso_path}")

    # ---------------------------------------------------------
    # 3. Create VirtualBox machine
    # ---------------------------------------------------------

    provider = VirtualBoxProvider(
        verbose=verbose
    )

    print(f"[3/5] Creating VM: {name}")

    disk_path = provider.create_vm_from_profile(
        name=name,
        profile=profile,
        cpus=resources.get("cpus"),
        memory_mb=resources.get("memory_mb"),
        disk_gb=resources.get("disk_gb"),
    )

    print(f"      -> disk: {disk_path}")

    # ---------------------------------------------------------
    # 4. Attach installation media and networking
    # ---------------------------------------------------------

    print(
        "[4/5] Attaching installation media "
        "and networking"
    )

    provider.attach_installation_media(
        name,
        vendor_iso=iso_path,
    )

    management = network.get("management", {})

    if management.get("enabled", True):
        slot = int(
            management.get("slot", 1)
        )

        interface = (
            provider.configure_management_nic(
                name,
                slot=slot,
            )
        )

        print(
            f"      -> management NIC slot "
            f"{slot}: {interface}"
        )

    # ---------------------------------------------------------
    # 5. Start
    # ---------------------------------------------------------

    if start.get("enabled", True):
        headless = bool(
            start.get("headless", False)
        )

        print(
            f"[5/5] Starting VM "
            f"(headless={headless})"
        )

        provider.start_vm(
            name,
            headless=headless,
        )

    else:
        print(
            "[5/5] VM created; "
            "start disabled by manifest"
        )

    print(
        f"\nMachine '{name}' created successfully."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create one Operation Crucible VM "
            "from a machine manifest."
        )
    )

    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=(
            "Machine manifest "
            f"(default: "
            f"{DEFAULT_MANIFEST.relative_to(REPO_ROOT)})"
        ),
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show VBoxManage commands.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    manifest_path = _repo_path(
        args.manifest
    )

    try:
        create_machine(
            manifest_path,
            verbose=args.verbose,
        )

    except (
        CrucibleError,
        FileNotFoundError,
        ValueError,
        KeyError,
    ) as exc:

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
