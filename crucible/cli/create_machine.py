from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from crucible.hypervisors.virtualbox import VirtualBoxProvider
from crucible.provisioning.image_detector import load_yaml, scan_images
from crucible.provisioning.ubuntu_autoinstall import (
    UbuntuAutoinstallError,
    build_seed_iso,
)


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
    if path.is_absolute():
        return path

    return REPO_ROOT / path


def load_machine_manifest(path: Path) -> dict[str, Any]:
    manifest = load_yaml(path)

    for key in ("name", "profile", "image_id"):
        if not manifest.get(key):
            raise CrucibleError(
                f"Manifest is missing required field: {key}"
            )

    return manifest


def load_os_profile(profile_name: str) -> dict[str, Any]:
    profile_path = PROFILE_DIR / f"{profile_name}.yml"

    if not profile_path.is_file():
        raise CrucibleError(
            f"OS profile not found: {profile_path}"
        )

    return load_yaml(profile_path)


def resolve_iso(image_id: str) -> Path:
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
    manifest = load_machine_manifest(manifest_path)

    name = str(manifest["name"])
    profile_name = str(manifest["profile"])
    image_id = str(manifest["image_id"])

    resources = manifest.get("resources", {})
    network = manifest.get("network", {})
    start = manifest.get("start", {})
    autoinstall = manifest.get("autoinstall", {})

    print(f"[1/6] Loading OS profile: {profile_name}")

    profile = load_os_profile(profile_name)

    print(f"[2/6] Resolving installation ISO: {image_id}")

    iso_path = resolve_iso(image_id)

    print(f"      -> {iso_path}")

    seed_iso_path: Path | None = None

    if isinstance(autoinstall, dict) and autoinstall.get(
        "enabled",
        False,
    ):
        print("[3/6] Generating Ubuntu autoinstall seed")

        seed_iso_path = build_seed_iso(
            manifest,
            repo_root=REPO_ROOT,
            verbose=verbose,
        )

        print(f"      -> {seed_iso_path}")
    else:
        print("[3/6] Autoinstall disabled")

    provider = VirtualBoxProvider(
        verbose=verbose
    )

    print(f"[4/6] Creating VM: {name}")

    disk_path = provider.create_vm_from_profile(
        name=name,
        profile=profile,
        cpus=resources.get("cpus"),
        memory_mb=resources.get("memory_mb"),
        disk_gb=resources.get("disk_gb"),
    )

    print(f"      -> disk: {disk_path}")

    print(
        "[5/6] Attaching installation media "
        "and networking"
    )

    provider.attach_installation_media(
        name,
        vendor_iso=iso_path,
        seed_iso=seed_iso_path,
    )

    internet = network.get("internet", {})

    if internet.get("enabled", False):
        slot = int(
            internet.get("slot", 1)
        )

        provider.configure_nat_nic(
            name,
            slot=slot,
        )

        print(
            f"      -> internet NIC slot "
            f"{slot}: NAT"
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

    if start.get("enabled", True):
        headless = bool(
            start.get("headless", False)
        )

        if (
            isinstance(autoinstall, dict)
            and autoinstall.get("enabled", False)
        ):
            print(
                f"[6/6] Starting unattended Ubuntu installation "
                f"(headless={headless})"
            )

            provider.start_ubuntu_autoinstall(
                name,
                headless=headless,
            )

        else:
            print(
                f"[6/6] Starting VM "
                f"(headless={headless})"
            )

            provider.start_vm(
                name,
                headless=headless,
            )

    else:
        print(
            "[6/6] VM created; "
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
        help="Show VBoxManage and seed-generation commands.",
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
        UbuntuAutoinstallError,
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
