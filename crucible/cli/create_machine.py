from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from crucible.hypervisors.virtualbox import VirtualBoxProvider
from crucible.provisioning.image_detector import load_yaml, scan_images

from crucible.validation.hardware import (
    validate_machine_hardware,
    validate_profile_hardware,
)
from crucible.provisioning.ubuntu_autoinstall import (
    UbuntuAutoinstallError,
    build_seed_iso,
)
from crucible.provisioning.kali_preseed import (
    KaliPreseedError,
    build_preseed,
)
from crucible.provisioning.preseed_server import (
    PreseedServer,
    PreseedServerError,
    virtualbox_nat_guest_host,
)
from crucible.provisioning.windows_unattend import (
    WindowsUnattendError,
    build_unattend_iso,
)
from crucible.networking.layout import (
    build_network_slot_layout,
    legacy_linux_interface_for_slot,
)
from crucible.configurations.catalog import (
    load_configuration_catalog,
    validate_manifest_configurations,
)
from crucible.hardening.catalog import (
    load_hardening_catalog,
)

from crucible.hardening.integration import (
    validate_manifest_hardening,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

IMAGE_CONFIG = REPO_ROOT / "config" / "images.yml"
PROFILE_DIR = REPO_ROOT / "profiles" / "os"
CONFIGURATION_CONFIG = (
    REPO_ROOT
    / "config"
    / "configurations.yml"
)
HARDENING_CONFIG = (
    REPO_ROOT
    / "config"
    / "hardening.yml"
)


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

    topology_interfaces = (
        network.get(
            "topology",
            [],
        )
    )

    internet = network.get(
        "internet",
        {},
    )

    management = network.get(
        "management",
        {},
    )

    internet_enabled = bool(
        internet.get(
            "enabled",
            False,
        )
    )

    management_enabled = bool(
        management.get(
            "enabled",
            True,
        )
    )

    try:
        network_layout = (
            build_network_slot_layout(
                len(
                    topology_interfaces
                ),
                internet_enabled=(
                    internet_enabled
                ),
                management_enabled=(
                    management_enabled
                ),
            )
        )

    except ValueError as exc:
        raise CrucibleError(
            f"Invalid NIC layout: {exc}"
        ) from exc

    autoinstall = manifest.get(
        "autoinstall",
        {},
    )

    unattended_enabled = (
        isinstance(
            autoinstall,
            dict,
        )
        and bool(
            autoinstall.get(
                "enabled",
                False,
            )
        )
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

    validate_profile_hardware(
        manifest,
        profile
    )

    configuration_catalog = (
        load_configuration_catalog(
            CONFIGURATION_CONFIG
        )
    )

    selected_configurations = (
        validate_manifest_configurations(
            manifest,
            profile,
            configuration_catalog,
        )
    )

    if selected_configurations:
        print(
            "      -> catalog configuration(s): "
            +
            ", ".join(
                definition.id

                for definition
                in selected_configurations
            )
        )

        print(
            "      -> configuration execution "
            "deferred to post-forge configuration stage"
        )

    hardening_catalog = (
        load_hardening_catalog(
            HARDENING_CONFIG,
            repo_root=(
                REPO_ROOT
            ),
        )
    )

    hardening_plans = (
        validate_manifest_hardening(
            manifest,

            selected_configurations,

            hardening_catalog,

            profile=profile,
        )
    )

    if hardening_plans:

        print(
            "      -> validated "
            f"{len(hardening_plans)} "
            "hardening plan(s)"
        )

        for (
            configuration_id,
            plan,
        ) in hardening_plans.items():

            print(
                "         "
                f"{configuration_id}: "
                f"{plan.benchmark.id} / "
                f"{plan.profile.id}"
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

    kali_installer_interface: (
        str | None
    ) = None

    kali_internet_slot: (
        int | None
    ) = None

    if (
        unattended_enabled
        and installer_backend
        == "debian-preseed"
    ):
        if not internet_enabled:
            raise CrucibleError(
                "Kali unattended installation "
                "requires the Crucible NAT NIC."
            )

        if not management_enabled:
            raise CrucibleError(
                "Kali unattended installation "
                "requires the Crucible management NIC."
            )

        kali_internet_slot = int(
            internet.get(
                "slot",
                0,
            )
        )

        try:
            kali_installer_interface = (
                legacy_linux_interface_for_slot(
                    kali_internet_slot
                )
            )

        except ValueError as exc:
            raise CrucibleError(
                "Could not resolve Kali "
                "installer network interface."
            ) from exc

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
    # Generate unattended-install configuration
    # ---------------------------------------------------------

    seed_iso_path: Path | None = None
    preseed_path: Path | None = None

    if unattended_enabled:

        if installer_backend == "ubuntu-autoinstall":

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


        elif installer_backend == "debian-preseed":

            print(
                "[3/6] Generating Kali "
                "preseed configuration"
            )

            preseed_path = build_preseed(
                manifest,
                repo_root=REPO_ROOT,
                verbose=verbose,
            )

            print(
                f"      -> {preseed_path}"
            )


        elif installer_backend == "windows-unattend":

            print(
                "[3/6] Generating Windows "
                "unattended-install media"
            )

            seed_iso_path = (
                build_unattend_iso(
                    manifest,
                    profile,
                    repo_root=REPO_ROOT,
                    verbose=verbose,
                )
            )

            print(
                f"      -> {seed_iso_path}"
            )


        else:

            raise CrucibleError(
                "Unsupported unattended "
                "installer backend: "
                f"{installer_backend or 'undefined'}"
            )

    else:

        print(
            "[3/6] Unattended install disabled"
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
    # NIC 1..N - persistent user topology
    # ---------------------------------------------------------

    for (
        topology_interface,
        expected_slot,
    ) in zip(
        topology_interfaces,
        network_layout.topology_slots,
    ):
        slot = int(
            topology_interface.get(
                "slot",
                expected_slot,
            )
        )

        label = str(
            topology_interface[
                "label"
            ]
        )

        mac_address = str(
            topology_interface[
                "mac_address"
            ]
        )

        attachment = (
            topology_interface[
                "attachment"
            ]
        )

        attachment_type = str(
            attachment[
                "type"
            ]
        )

        provider.configure_topology_nic(
            name,
            slot=slot,
            attachment_type=(
                attachment_type
            ),
            mac_address=(
                mac_address
            ),
            network_name=(
                attachment.get(
                    "network"
                )
            ),
            host_adapter=(
                attachment.get(
                    "adapter"
                )
            ),
        )

        print(
            f"      -> topology NIC "
            f"slot {slot}: "
            f"{label} "
            f"({attachment_type})"
        )

        print(
            f"      -> topology MAC: "
            f"{mac_address}"
        )

    # ---------------------------------------------------------
    # Crucible NAT / Internet overlay
    # ---------------------------------------------------------

    if internet_enabled:
        if (
            network_layout.internet_slot
            is None
        ):
            raise CrucibleError(
                "Internet NIC slot "
                "was not resolved."
            )

        slot = int(
            internet.get(
                "slot",
                network_layout.internet_slot,
            )
        )

        internet_mac = str(
            internet.get(
                "mac_address",
                "",
            )
        ).strip()

        provider.configure_nat_nic(
            name,
            slot=slot,
            mac_address=(
                internet_mac
                or None
            ),
        )

        if (
            unattended_enabled
            and installer_backend
            == "debian-preseed"
        ):
            provider.set_nat_localhost_reachable(
                name,
                slot=slot,
                enabled=True,
            )

        print(
            f"      -> Crucible Internet "
            f"NIC slot {slot}: NAT"
        )

        if internet_mac:
            print(
                f"      -> Internet MAC: "
                f"{internet_mac}"
            )

        if (
            unattended_enabled
            and installer_backend
            == "debian-preseed"
        ):
            print(
                "      -> NAT host-loopback "
                "access enabled for preseed"
            )

    # ---------------------------------------------------------
    # Crucible management overlay
    # ---------------------------------------------------------

    if management_enabled:
        if (
            network_layout.management_slot
            is None
        ):
            raise CrucibleError(
                "Management NIC slot "
                "was not resolved."
            )

        slot = int(
            management.get(
                "slot",
                network_layout.management_slot,
            )
        )

        management_mac = str(
            management.get(
                "mac_address",
                "",
            )
        ).strip()

        interface = (
            provider.configure_management_nic(
                name,
                slot=slot,
                mac_address=(
                    management_mac
                    or None
                ),
            )
        )

        print(
            f"      -> Crucible management "
            f"NIC slot {slot}: "
            f"{interface.name}"
        )

        if management_mac:
            print(
                f"      -> management MAC: "
                f"{management_mac}"
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

        if unattended_enabled:

            if installer_backend == "ubuntu-autoinstall":
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

            elif installer_backend == "debian-preseed":
                if preseed_path is None:
                    raise CrucibleError(
                        "Kali preseed path was "
                        "not generated."
                    )

                print(
                    "[6/6] Starting unattended "
                    "Kali installation "
                    f"(headless={headless})"
                )

                if kali_internet_slot is None:
                    raise CrucibleError(
                        "Kali NAT slot was not resolved."
                    )

                preseed_guest_host = (
                    virtualbox_nat_guest_host(
                        kali_internet_slot
                    )
                )

                print(
                    "      -> Kali installer "
                    f"interface: "
                    f"{kali_installer_interface}"
                )

                print(
                    "      -> Kali NAT slot: "
                    f"NIC {kali_internet_slot}"
                )

                print(
                    "      -> Kali NAT host: "
                    f"{preseed_guest_host}"
                )

                with PreseedServer(
                    preseed_path,
                    guest_host=preseed_guest_host,
                ) as preseed_server:

                    print(
                        "      -> preseed available "
                        "to guest:"
                    )

                    print(
                        f"         "
                        f"{preseed_server.guest_url}"
                    )

                    if kali_installer_interface is None:
                        raise CrucibleError(
                            "Kali installer interface "
                            "was not resolved."
                        )

                    provider.start_kali_preseed_install(
                        name,
                        preseed_url=(
                            preseed_server.guest_url
                        ),
                        installer_interface=(
                            kali_installer_interface
                        ),
                        headless=headless,
                    )

                    print(
                        "      -> waiting for Kali "
                        "installer to fetch preseed"
                    )

                    preseed_server.wait_for_fetch(
                        timeout=180.0,
                    )

                    print(
                        "      -> Kali installer "
                        "fetched preseed successfully"
                    )

            elif installer_backend == "windows-unattend":

                print(
                    "[6/6] Starting unattended "
                    "Windows installation "
                    f"(headless={headless})"
                )

                windows_boot = installer.get(
                    "boot",
                    {},
                )

                boot_delay_seconds = float(
                    windows_boot.get(
                        "dvd_prompt_delay_seconds",
                        3.0,
                    )
                )

                provider.start_windows_unattended_install(
                    name,
                    headless=headless,
                    boot_delay_seconds=boot_delay_seconds,
                )
                
            else:
                raise CrucibleError(
                    "Unsupported unattended "
                    "installer backend: "
                    f"{installer_backend or 'undefined'}"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create one Operation Crucible VM "
            "from a machine manifest."
        )
    )

    parser.add_argument(
        "manifest",
        type=Path,
        help="Machine manifest path.",
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
        KaliPreseedError,
        PreseedServerError,
        FileNotFoundError,
        ValueError,
        KeyError,
        WindowsUnattendError,
    ) as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
