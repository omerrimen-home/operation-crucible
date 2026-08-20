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
from crucible.validation.hardware import (
    validate_machine_hardware,
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

    validate_machine_hardware(
        manifest
    )
    
    return manifest


def load_os_profile(profile_name: str) -> dict[str, Any]:
    profile_path = PROFILE_DIR / f"{profile_name}.yml"

    if not profile_path.is_file():
        raise CrucibleError(
            f"OS profile not found: {profile_path}"
        )

    return load_yaml(profile_path)


def resolve_iso(
    image_id: str,
    *,
    expected_media_type: str | None = None,
) -> Path:
    
    scan, _ = scan_images(IMAGE_CONFIG)

    records = (
        scan
        .get("recognized", {})
        .get(image_id, [])
    )

    if expected_media_type is not None:
        wanted = (
            expected_media_type
            .strip()
            .lower()
        )

        records = [
            record
            for record in records
            if str(
                record.get(
                    "media_type",
                    "",
                )
            ).strip().lower()
            == wanted
        ]

    if not records:
        if expected_media_type:
            raise CrucibleError(
                f"No '{expected_media_type}' ISO "
                f"recognized for image_id "
                f"'{image_id}'."
            )

        raise CrucibleError(
            f"No ISO recognized for image_id "
            f"'{image_id}'. "
            "Run: "
            "python3 -m "
            "crucible.provisioning.image_detector "
            "--json"
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
    manifest = load_machine_manifest(
        manifest_path
    )

    name = str(
        manifest["name"]
    )

    profile_name = str(
        manifest["profile"]
    )

    image_id = str(
        manifest["image_id"]
    )

    # ---------------------------------------------------------
    # Machine manifest sections
    # ---------------------------------------------------------

    resources = manifest.get(
        "resources",
        {},
    )

    machine_vbox = manifest.get(
        "virtualbox",
        {},
    )

    machine_graphics = machine_vbox.get(
        "graphics",
        {},
    )

    network = manifest.get(
        "network",
        {},
    )

    autoinstall = manifest.get(
        "autoinstall",
        {},
    )

    start = manifest.get(
        "start",
        {},
    )

    # ---------------------------------------------------------
    # Load OS profile
    # ---------------------------------------------------------

    print(
        f"[1/6] Loading OS profile: "
        f"{profile_name}"
    )

    profile = load_os_profile(
        profile_name
    )

    installer = profile.get(
        "installer",
        {},
    )

    installer_backend = str(
        installer.get(
            "backend",
            "",
        )
    ).strip().lower()

    expected_media_type = installer.get(
        "media_type"
    )

    profile_os = profile.get(
        "os",
        {},
    )

    os_flavor = str(
        profile_os.get(
            "flavor",
            "",
        )
    ).lower()
    # ---------------------------------------------------------
    # Resolve installation ISO
    # ---------------------------------------------------------

    print(
        f"[2/6] Resolving installation ISO: "
        f"{image_id}"
    )

    iso_path = resolve_iso(
        image_id,
        expected_media_type=(
            str(expected_media_type)
            if expected_media_type
            else None
        ),
    )

    print(
        f"      -> {iso_path}"
    )

    # ---------------------------------------------------------
    # Generate unattended-install seed
    # ---------------------------------------------------------

    seed_iso_path: Path | None = None

    if (
        isinstance(autoinstall, dict)
        and autoinstall.get(
            "enabled",
            False,
        )
    ):
        print(
            "[3/6] Generating Ubuntu "
            "autoinstall seed"
        )

        seed_iso_path = build_seed_iso(
            manifest,
            repo_root=REPO_ROOT,
            verbose=verbose,
        )

        print(
            f"      -> {seed_iso_path}"
        )

    else:
        print(
            "[3/6] Autoinstall disabled"
        )

    # ---------------------------------------------------------
    # Initialize VirtualBox provider
    # ---------------------------------------------------------

    provider = VirtualBoxProvider(
        verbose=verbose
    )

    # ---------------------------------------------------------
    # Create VM and primary disk
    # ---------------------------------------------------------

    print(
        f"[4/6] Creating VM: {name}"
    )

    disk_path = (
        provider.create_vm_from_profile(
            name=name,
            profile=profile,

            cpus=resources.get(
                "cpus"
            ),

            memory_mb=resources.get(
                "memory_mb"
            ),

            disk_gb=resources.get(
                "disk_gb"
            ),

            firmware=machine_vbox.get(
                "firmware"
            ),

            graphics_controller=(
                machine_graphics.get(
                    "controller"
                )
            ),

            vram_mb=machine_graphics.get(
                "vram_mb"
            ),

            accelerate_3d=(
                machine_graphics.get(
                    "accelerate_3d"
                )
            ),
        )
    )

    print(
        f"      -> disk: {disk_path}"
    )

    # ---------------------------------------------------------
    # Installation media
    # ---------------------------------------------------------

    print(
        "[5/6] Attaching installation media "
        "and networking"
    )

    provider.attach_installation_media(
        name,
        vendor_iso=iso_path,
        seed_iso=seed_iso_path,
    )

    # ---------------------------------------------------------
    # NIC 1 - temporary NAT / internet
    # ---------------------------------------------------------

    internet = network.get(
        "internet",
        {},
    )

    if internet.get(
        "enabled",
        False,
    ):
        slot = int(
            internet.get(
                "slot",
                1,
            )
        )

        provider.configure_nat_nic(
            name,
            slot=slot,
        )

        print(
            f"      -> internet NIC slot "
            f"{slot}: NAT"
        )

    # ---------------------------------------------------------
    # NIC 2 - Crucible management / Ansible
    # ---------------------------------------------------------

    management = network.get(
        "management",
        {},
    )

    if management.get(
        "enabled",
        True,
    ):
        slot = int(
            management.get(
                "slot",
                2,
            )
        )

        interface = (
            provider.configure_management_nic(
                name,
                slot=slot,
            )
        )

        print(
            f"      -> management NIC slot "
            f"{slot}: {interface.name}"
        )

    # ---------------------------------------------------------
    # NIC 3+ - user-defined internal networks
    # ---------------------------------------------------------

    internal_networks = network.get(
        "internal",
        [],
    )

    for index, internal in enumerate(
        internal_networks,
        start=3,
    ):
        slot = int(
            internal.get(
                "slot",
                index,
            )
        )

        network_name = str(
            internal["name"]
        )

        provider.configure_internal_nic(
            name,
            slot=slot,
            network_name=network_name,
        )

        print(
            f"      -> internal NIC slot "
            f"{slot}: {network_name}"
        )

    # ---------------------------------------------------------
    # Start VM
    # ---------------------------------------------------------

    if start.get(
        "enabled",
        True,
    ):
        headless = bool(
            start.get(
                "headless",
                False,
            )
        )

        if (
            isinstance(autoinstall, dict)
            and autoinstall.get(
                "enabled",
                False,
            )
        ):
            print(
                "[6/6] Starting unattended "
                "Ubuntu installation "
                f"(headless={headless})"
            )

            provider.start_ubuntu_autoinstall(
                name,
                headless=headless,
                flavor=os_flavor,
            )

        else:
            print(
                "[6/6] Starting VM "
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
        f"\nMachine '{name}' "
        "created successfully."
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
