#!/usr/bin/env python3

from __future__ import annotations

import getpass
import secrets
import shutil
import string
import subprocess
import sys
from pathlib import Path
from typing import Any
import socket
import yaml
import time
import re
from crucible.cli.create_machine import (
    create_machine,
    load_os_profile,
)
from crucible.validation.hardware import (
    CPU_MIN,
    CPU_MAX,
    MEMORY_MB_MIN,
    MEMORY_MB_MAX,
    DISK_GB_MIN,
    DISK_GB_MAX,
    VRAM_MB_MIN,
    VRAM_MB_MAX,
    GRAPHICS_CONTROLLERS,
    MAX_TOPOLOGY_NICS,
)
from crucible.networking.management import (
    allocate_management_address,
    management_mac_for_machine,
    internet_mac_for_machine,
)

from crucible.networking.layout import (
    build_network_slot_layout,
)
from crucible.hypervisors.virtualbox import (
    VirtualBoxProvider,
    VirtualBoxError,
)
from crucible.cli.create_machine import (
    CrucibleError,
    create_machine,
    load_os_profile,
)
from crucible.provisioning.ubuntu_autoinstall import (
    UbuntuAutoinstallError,
)
from crucible.provisioning.kali_preseed import (
    KaliPreseedError,
)
from crucible.provisioning.preseed_server import (
    PreseedServerError,
)
from crucible.provisioning.windows_unattend import (
    WindowsUnattendError,
)
from crucible.networking.topology import (
    TOPOLOGY_ATTACHMENT_TYPES,
    TOPOLOGY_LABEL_PATTERN,
    TopologyConfigurationError,
    build_dhcp_ipv4_configuration,
    build_static_ipv4_configuration,
    topology_mac_for_machine,
)
from crucible.ssh.identity import (
    SshIdentity,
    SshIdentityError,
    create_machine_ssh_identity,
    generate_instance_serial,
    load_machine_ssh_identity,
    reset_machine_known_hosts,
)

REPO_ROOT = Path(__file__).resolve().parent

MACHINE_MANIFEST_DIR = (
    REPO_ROOT
    / ".crucible"
    / "manifests"
    / "machines"
)

LAB_MANIFEST_DIR = (
    REPO_ROOT
    / ".crucible"
    / "manifests"
    / "labs"
)

ANSIBLE_RUNTIME_DIR = (
    REPO_ROOT
    / ".crucible"
    / "ansible"
)

WINDOWS_BOOTSTRAP_COMPLETE_PATH = (
    r"C:\ProgramData\Crucible\bootstrap-complete"
)

WINDOWS_BOOTSTRAP_FAILED_PATH = (
    r"C:\ProgramData\Crucible\bootstrap-failed"
)

SUPPORTED_VM_COUNT = 1

SUPPORTED_OPERATING_SYSTEMS = {
    "1": {
        "name": "Ubuntu Server",
        "version": "26.04",
        "profile": "ubuntu-26.04-server",
        "image_id": "ubuntu-26.04-server",
        "vm_name_prefix": "ubuntu-server",
    },

    "2": {
        "name": "Ubuntu Desktop",
        "version": "26.04",
        "profile": "ubuntu-26.04-desktop",
        "image_id": "ubuntu-26.04-desktop",
        "vm_name_prefix": "ubuntu-desktop",
    },
    "3": {
        "name": "Kali Linux",
        "version": "Rolling",
        "profile": "kali-rolling",
        "image_id": "kali-rolling",
        "vm_name_prefix": "kali",
    },
    "4": {
        "name": "Windows 10",
        "version": "64-bit",
        "profile": "windows-10",
        "image_id": "windows-10",
        "vm_name_prefix": "win10",
    },
    "5": {
        "name": "Windows 11",
        "version": "64-bit",
        "profile": "windows-11",
        "image_id": "windows-11",
        "vm_name_prefix": "win11",
    },
    "6": {
        "name": "Windows Server 2022",
        "version": "64-bit",
        "profile": "windows-server-2022",
        "image_id": "windows-server-2022",
        "vm_name_prefix": "ws2022",
    },
}

DEFAULT_AUTOINSTALL = {
    "realname": "Crucible User",
    "username": "crucible",
    "locale": "en_CA.UTF-8",
    "timezone": "America/Toronto",
    "keyboard_layout": "us",
    "keyboard_variant": "",
    "storage_layout": "direct",
    "updates": "security",
    "shutdown": "reboot",
    "ssh_install_server": True,
    "ssh_allow_password": True,
}

DEFAULT_WINDOWS_UNATTEND = {
    "realname": "Crucible User",
    "username": "crucible",

    # The Microsoft ISO is normally en-US media.
    # Keep the actual Windows UI language en-US for
    # compatibility, while using Canadian locale settings.
    "ui_language": "en-US",
    "input_locale": "en-US",
    "system_locale": "en-CA",
    "user_locale": "en-CA",

    # Windows uses Windows timezone IDs, not IANA names.
    "timezone": "Eastern Standard Time",

    "organization": "Operation Crucible",
}

USE_COLOR = sys.stdout.isatty()

RESET = "\033[0m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""
GOLD = "\033[38;5;214m" if USE_COLOR else ""
RED = "\033[31m" if USE_COLOR else ""
GREEN = "\033[32m" if USE_COLOR else ""
CYAN = "\033[36m" if USE_COLOR else ""
YELLOW = "\033[33m" if USE_COLOR else ""


class CrucibleForgeError(RuntimeError):
    """Expected error raised by the human-facing Crucible Forge."""


def clear_screen() -> None:
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def show_banner() -> None:
    clear_screen()

    print(
        GOLD
        + r"""
                   (             )
                    )           (
                   (             )
                      )       (
                 .-----------------.
                /                   \
               /      CRUCIBLE       \
              |         FORGE         |
               \                     /
                '-------------------'
                     \   |   /
                      \  |  /
                   ____\_|_/____
                  /             \
                 /_______________\
"""
        + RESET
    )

    print(f"{BOLD}       OPERATION CRUCIBLE{RESET}")
    print(f"{DIM}       Infrastructure forged to order.{RESET}")
    print()
    print(
        "Welcome to the Crucible Forge.\n"
        "Describe the environment you need and Crucible will construct it."
    )
    print()


def ask_yes_no(prompt: str, *, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"

    while True:
        answer = input(f"{prompt} {suffix}: ").strip().lower()

        if not answer:
            return default

        if answer in {"y", "yes"}:
            return True

        if answer in {"n", "no"}:
            return False

        print(f"{RED}Please answer yes or no.{RESET}")


def ask_with_default(prompt: str, default: str) -> str:
    answer = input(f"{prompt} [{default}]: ").strip()
    return answer if answer else default


def ask_vm_count() -> int:
    while True:
        answer = input(
            f"{BOLD}How many VMs are in your topology?{RESET} [1]: "
        ).strip()

        if not answer:
            answer = "1"

        if answer == "1":
            return 1

        print()
        print(
            f"{RED}Crucible currently supports exactly one VM.{RESET}"
        )
        print()


def ask_operating_system() -> dict[str, Any]:
    print()
    print(f"{BOLD}What operating system are you looking for?{RESET}")
    print()

    for key, os_info in SUPPORTED_OPERATING_SYSTEMS.items():
        print(f"  [{key}] {os_info['name']} {os_info['version']}")

    print()

    while True:
        answer = input("Selection [1]: ").strip() or "1"

        if answer in SUPPORTED_OPERATING_SYSTEMS:
            return dict(SUPPORTED_OPERATING_SYSTEMS[answer])

        print(
            f"{RED}That operating system is not currently supported "
            f"by Crucible.{RESET}"
        )

def show_network_slot_plan(
    topology_interfaces: (
        list[dict[str, Any]]
    ),
) -> None:

    layout = (
        build_network_slot_layout(
            len(
                topology_interfaces
            ),
            internet_enabled=True,
            management_enabled=True,
        )
    )

    print()
    print(
        f"{BOLD}"
        "Network interface layout:"
        f"{RESET}"
    )
    print()

    for interface, slot in zip(
        topology_interfaces,
        layout.topology_slots,
    ):
        label = str(
            interface["label"]
        )

        attachment = (
            interface[
                "attachment"
            ]
        )

        attachment_type = str(
            attachment["type"]
        )

        type_label = (
            TOPOLOGY_ATTACHMENT_TYPES[
                attachment_type
            ]
        )

        ipv4 = interface[
            "ipv4"
        ]

        method = str(
            ipv4["method"]
        )

        print(
            f"  NIC {slot:<2} : "
            f"{label} "
            f"({type_label})"
        )

        if method == "dhcp":
            print(
                "           IPv4: DHCP"
            )

        else:
            print(
                "           IPv4: "
                f"{ipv4['address']}"
            )

            gateway = (
                ipv4.get(
                    "gateway"
                )
            )

            print(
                "           Gateway: "
                f"{gateway or 'none'}"
            )

    if (
        layout.internet_slot
        is not None
    ):
        print(
            f"  NIC "
            f"{layout.internet_slot:<2} : "
            "Crucible NAT / Internet"
        )

    if (
        layout.management_slot
        is not None
    ):
        print(
            f"  NIC "
            f"{layout.management_slot:<2} : "
            "Crucible management"
        )

    print()

VM_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$"
)

WINDOWS_COMPUTER_NAME_PATTERN = re.compile(
        r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,13}[A-Za-z0-9])?$"
    )

def validate_windows_computer_name(name: str) -> None:
        if not name:
            raise CrucibleForgeError(
                "Windows computer name may not be empty."
            )

        try:
            encoded = name.encode("ascii")
        except UnicodeEncodeError as exc:
            raise CrucibleForgeError(
                "Windows computer names must use ASCII characters."
            ) from exc

        if len(encoded) > 15:
            raise CrucibleForgeError(
                "Windows computer names may not exceed 15 characters."
            )

        if not WINDOWS_COMPUTER_NAME_PATTERN.fullmatch(name):
            raise CrucibleForgeError(
                "Windows computer names may contain only letters, "
                "numbers, and hyphens, and must begin and end "
                "with a letter or number."
            )

        if name.isdigit():
            raise CrucibleForgeError(
                "Windows computer names may not contain only numbers."
            )

def get_reserved_vm_names() -> set[str]:
    """
    Return VM names that Crucible should not reuse.

    Includes registered VirtualBox VMs and leftover
    Crucible VM directories from incomplete builds.
    """

    provider = VirtualBoxProvider(
        verbose=False
    )

    names = {
        machine.name
        for machine in provider.list_vms()
    }

    if provider.vm_base_folder.is_dir():
        for path in (
            provider.vm_base_folder.iterdir()
        ):
            if path.is_dir():
                names.add(
                    path.name
                )

    return names

def get_default_vm_name(
    os_info: dict[str, Any],
    reserved_names: set[str],
) -> str:
    """
    Generate the next numbered name for an OS.

    Examples:

        ubuntu-server-01
        ubuntu-server-02
        ubuntu-server-03
    """

    prefix = str(
        os_info["vm_name_prefix"]
    )

    pattern = re.compile(
        rf"^{re.escape(prefix)}-(\d+)$",
        re.IGNORECASE,
    )

    highest_number = 0

    for name in reserved_names:
        match = pattern.match(
            name
        )

        if not match:
            continue

        highest_number = max(
            highest_number,
            int(match.group(1)),
        )

    next_number = (
        highest_number + 1
    )

    return (
        f"{prefix}-"
        f"{next_number:02d}"
    )

def get_machine_instance_serial(
    machine_manifest_path: Path,
) -> str:
    with machine_manifest_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        manifest = yaml.safe_load(
            file
        )

    instance = manifest.get(
        "instance",
        {},
    )

    serial = str(
        instance.get(
            "serial",
            "",
        )
    ).strip()

    if not serial:
        raise CrucibleForgeError(
            "Machine manifest is missing "
            "instance.serial."
        )

    return serial

def get_guest_family(
    os_info: dict[str, Any],
) -> str:
    profile = load_os_profile(
        str(
            os_info[
                "profile"
            ]
        )
    )

    return str(
        profile.get(
            "os",
            {},
        ).get(
            "family",
            "",
        )
    ).strip().lower()

def ask_vm_name(
    os_info: dict[str, Any],
) -> str:
    reserved_names = (
        get_reserved_vm_names()
    )

    default_name = get_default_vm_name(
        os_info,
        reserved_names,
    )

    print()
    print(
        f"{BOLD}Machine identity:{RESET}"
    )
    print()

    while True:
        vm_name = ask_with_default(
            "VirtualBox VM name",
            default_name,
        ).strip()

        if not VM_NAME_PATTERN.fullmatch(
            vm_name
        ):
            print(
                f"{RED}"
                "VM names may contain letters, "
                "numbers, periods, underscores, "
                "and hyphens, and must begin "
                "with a letter or number."
                f"{RESET}"
            )
            continue

        if vm_name in reserved_names:
            print(
                f"{RED}"
                f"A VirtualBox/Crucible machine "
                f"named '{vm_name}' already exists."
                f"{RESET}"
            )
            continue

        return vm_name

def ask_hardware_defaults(
    os_info: dict[str, Any],
) -> dict[str, Any]:
    profile = load_os_profile(
        str(os_info["profile"])
    )

    defaults = profile.get(
        "defaults",
        {},
    )

    virtualbox = profile.get(
        "virtualbox",
        {},
    )

    requirements = profile.get(
        "requirements",
        {},
    )

    graphics = virtualbox.get(
        "graphics",
        {},
    )

    security = virtualbox.get(
        "security",
        {},
    )

    hardware = {
        "cpus": int(
            defaults.get("cpus", 2)
        ),
        "memory_mb": int(
            defaults.get("memory_mb", 2048)
        ),
        "disk_gb": int(
            defaults.get("disk_gb", 20)
        ),
        "firmware": str(
            virtualbox.get("firmware", "efi")
        ),
        "graphics_controller": str(
            graphics.get(
                "controller",
                "vmsvga",
            )
        ),
        "vram_mb": int(
            graphics.get("vram_mb", 32)
        ),
        "accelerate_3d": bool(
            graphics.get(
                "accelerate_3d",
                False,
            )
        ),
        "topology_interfaces": [],
    }

    print()
    print(f"{BOLD}VM hardware defaults:{RESET}")
    print()

    print(
        f"  CPUs               : "
        f"{hardware['cpus']}"
    )
    print(
        f"  Memory             : "
        f"{hardware['memory_mb']} MB"
    )
    print(
        f"  Virtual disk       : "
        f"{hardware['disk_gb']} GB"
    )
    print(
        f"  Video memory       : "
        f"{hardware['vram_mb']} MB"
    )
    print(
        f"  Firmware           : "
        f"{hardware['firmware'].upper()}"
    )
    print(
        f"  TPM                : "
        f"{security.get('tpm', 'none')}"
    )

    print(
        f"  Secure Boot        : "
        f"{'yes' if security.get('secure_boot', False) else 'no'}"
    )
    print(
        f"  Graphics controller: "
        f"{hardware['graphics_controller']}"
    )
    print(
        f"  3D acceleration    : "
        f"{'yes' if hardware['accelerate_3d'] else 'no'}"
    )
    print(
    "  Internal networks  : none"
    )
    print(
        "  Crucible Internet  : NIC 1 "
        "(appended after internal NICs)"
    )
    print(
        "  Crucible management: NIC 2 "
        "(appended after Internet NIC)"
    )
    print(
        "  Disk type          : "
        "Dynamically allocated VDI"
    )
    print()

    if ask_yes_no(
        f"{BOLD}Use VM hardware defaults?{RESET}",
        default=True,
    ):
        return hardware

    cpu_minimum = max(
        CPU_MIN,
        int(
            requirements.get(
                "min_cpus",
                CPU_MIN,
            )
        ),
    )

    memory_minimum = max(
        MEMORY_MB_MIN,
        int(
            requirements.get(
                "min_memory_mb",
                MEMORY_MB_MIN,
            )
        ),
    )

    disk_minimum = max(
        DISK_GB_MIN,
        int(
            requirements.get(
                "min_disk_gb",
                DISK_GB_MIN,
            )
        ),
    )

    print()
    print(
        f"{BOLD}Custom VM hardware{RESET}"
    )
    print()

    hardware["cpus"] = ask_int_with_default(
        "CPUs",
        hardware["cpus"],
        minimum=cpu_minimum,
        maximum=CPU_MAX,
    )

    hardware["memory_mb"] = ask_int_with_default(
        "Memory (MB)",
        hardware["memory_mb"],
        minimum=memory_minimum,
        maximum=MEMORY_MB_MAX,
    )

    hardware["disk_gb"] = ask_int_with_default(
        "Virtual disk (GB)",
        hardware["disk_gb"],
        minimum=disk_minimum,
        maximum=DISK_GB_MAX,
    )

    hardware["vram_mb"] = ask_int_with_default(
        "Video memory (MB)",
        hardware["vram_mb"],
        minimum=VRAM_MB_MIN,
        maximum=VRAM_MB_MAX,
    )

    required_firmware = requirements.get(
        "firmware"
    )

    if required_firmware:
        hardware["firmware"] = str(
            required_firmware
        ).lower()

        print(
            f"Firmware fixed at "
            f"{hardware['firmware'].upper()} "
            f"by OS requirements."
        )

    else:
        use_efi = ask_yes_no(
            "Use EFI firmware?",
            default=(
                hardware["firmware"]
                != "bios"
            ),
        )

        hardware["firmware"] = (
            "efi"
            if use_efi
            else "bios"
        )

    hardware["graphics_controller"] = (
        ask_choice(
            "Graphics controller",
            hardware["graphics_controller"],
            GRAPHICS_CONTROLLERS,
        )
    )

    if (
        hardware["graphics_controller"]
        == "vboxvga"
    ):
        hardware["accelerate_3d"] = False

        print(
            f"{YELLOW}"
            "3D acceleration disabled because "
            "VBoxVGA is the legacy controller."
            f"{RESET}"
        )

    else:
        hardware["accelerate_3d"] = (
            ask_yes_no(
                "Enable 3D acceleration?",
                default=hardware[
                    "accelerate_3d"
                ],
            )
        )

    return hardware

def ask_topology_attachment_type(
) -> str:
    print()
    print(
        f"{BOLD}"
        "Interface type:"
        f"{RESET}"
    )
    print()
    print(
        "  [1] Internal Network "
        "(VirtualBox intnet)"
    )
    print(
        "  [2] Bridged Adapter "
        "(host LAN/WLAN)"
    )
    print()

    while True:
        answer = input(
            "Selection [1]: "
        ).strip() or "1"

        if answer == "1":
            return "intnet"

        if answer == "2":
            return "bridged"

        print(
            f"{RED}"
            "Choose 1 or 2."
            f"{RESET}"
        )

def ask_bridged_adapter(
) -> str:
    provider = VirtualBoxProvider(
        verbose=False
    )

    adapters = (
        provider
        .list_bridged_interface_names()
    )

    if not adapters:
        raise CrucibleForgeError(
            "VirtualBox did not report any "
            "bridged host interfaces."
        )

    print()
    print(
        f"{BOLD}"
        "Available host adapters:"
        f"{RESET}"
    )
    print()

    for number, adapter in enumerate(
        adapters,
        start=1,
    ):
        print(
            f"  [{number}] {adapter}"
        )

    print()

    while True:
        answer = input(
            "Host adapter [1]: "
        ).strip() or "1"

        try:
            index = (
                int(answer) - 1
            )

        except ValueError:
            print(
                f"{RED}"
                "Enter an adapter number."
                f"{RESET}"
            )
            continue

        if (
            0
            <= index
            < len(adapters)
        ):
            return adapters[
                index
            ]

        print(
            f"{RED}"
            "That adapter number "
            "is not available."
            f"{RESET}"
        )

def ask_topology_ipv4_configuration(
) -> dict[str, Any]:
    print()

    use_dhcp = ask_yes_no(
        "Use DHCP on this interface?",
        default=True,
    )

    if use_dhcp:
        return (
            build_dhcp_ipv4_configuration()
        )

    while True:
        print()

        address = input(
            "IPv4 address: "
        ).strip()

        if not address:
            print(
                f"{RED}"
                "A static interface requires "
                "an IPv4 address."
                f"{RESET}"
            )
            continue

        subnet_mask = (
            ask_with_default(
                "Subnet mask",
                "255.255.255.0",
            )
        )

        gateway = input(
            "Default gateway "
            "[none]: "
        ).strip()

        try:
            return (
                build_static_ipv4_configuration(
                    address=address,
                    subnet_mask=subnet_mask,
                    gateway=(
                        gateway
                        if gateway
                        else None
                    ),
                )
            )

        except (
            TopologyConfigurationError
        ) as exc:
            print()
            print(
                f"{RED}"
                f"{exc}"
                f"{RESET}"
            )
            print(
                f"{YELLOW}"
                "Please enter the static "
                "IPv4 configuration again."
                f"{RESET}"
            )

def ask_topology_interfaces(
) -> list[dict[str, Any]]:
    """
    Ask the user for persistent topology NICs.

    These interfaces become NIC 1..N.

    Crucible Internet and management interfaces are
    appended afterward.
    """

    print()
    print(
        f"{BOLD}"
        "Persistent topology interfaces"
        f"{RESET}"
    )
    print()

    print(
        "These interfaces remain part of the "
        "lab topology. Crucible's temporary "
        "Internet and management adapters will "
        "be appended afterward."
    )
    print()

    count = ask_int_with_default(
        "Number of topology interfaces",
        0,
        minimum=0,
        maximum=MAX_TOPOLOGY_NICS,
    )

    interfaces: list[
        dict[str, Any]
    ] = []

    used_labels: set[str] = set()
    used_topology_networks: (
        set[str]
    ) = set()

    for slot in range(
        1,
        count + 1,
    ):
        print()
        print(
            f"{CYAN}"
            "------------------------------------------"
            f"{RESET}"
        )
        print(
            f"{BOLD}"
            f"Topology NIC {slot}"
            f"{RESET}"
        )
        print(
            f"{CYAN}"
            "------------------------------------------"
            f"{RESET}"
        )

        default_label = (
            f"net{slot}"
        )

        while True:
            label = ask_with_default(
                "Interface label",
                default_label,
            ).strip()

            if not (
                TOPOLOGY_LABEL_PATTERN
                .fullmatch(
                    label
                )
            ):
                print(
                    f"{RED}"
                    "Interface labels may contain "
                    "letters, numbers, periods, "
                    "underscores and hyphens."
                    f"{RESET}"
                )
                continue

            if label in used_labels:
                print(
                    f"{RED}"
                    "Interface labels must "
                    "be unique."
                    f"{RESET}"
                )
                continue

            break

        attachment_type = (
            ask_topology_attachment_type()
        )

        if (
            attachment_type
            == "intnet"
        ):
            while True:
                network_name = (
                    ask_with_default(
                        "Internal network name",
                        label,
                    )
                ).strip()

                if not network_name:
                    print(
                        f"{RED}"
                        "Internal network name "
                        "may not be empty."
                        f"{RESET}"
                    )
                    continue

                if (
                    network_name
                    in used_topology_networks
                ):
                    print(
                        f"{RED}"
                        "This VM is already "
                        "attached to that internal "
                        "network."
                        f"{RESET}"
                    )
                    continue

                break

            attachment = {
                "type": "intnet",
                "network": (
                    network_name
                ),
            }

            used_topology_networks.add(
                network_name
            )

        elif (
            attachment_type
            == "bridged"
        ):
            host_adapter = (
                ask_bridged_adapter()
            )

            attachment = {
                "type": "bridged",
                "adapter": (
                    host_adapter
                ),
            }

        else:
            raise CrucibleForgeError(
                "Unsupported topology "
                "attachment type reached "
                f"Forge logic: "
                f"{attachment_type}"
            )

        ipv4 = (
            ask_topology_ipv4_configuration()
        )

        interfaces.append(
            {
                "label": label,
                "attachment": attachment,
                "ipv4": ipv4,
            }
        )

        used_labels.add(
            label
        )

    return interfaces

def detect_ssh_public_key() -> str | None:
    candidates = (
        Path.home() / ".ssh" / "id_ed25519.pub",
        Path.home() / ".ssh" / "id_ecdsa.pub",
        Path.home() / ".ssh" / "id_rsa.pub",
    )

    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue

        if value:
            return value

    return None

def wait_for_ssh_authentication(
    *,
    host: str,
    username: str,
    ssh_identity: SshIdentity,
    timeout: int = 300,
    poll_interval: float = 3.0,
) -> None:
    """
    Wait until the guest accepts Crucible's dedicated
    per-instance SSH identity.
    """

    print()
    print(
        f"{CYAN}"
        "Waiting for SSH authentication..."
        f"{RESET}"
    )

    deadline = (
        time.monotonic()
        + timeout
    )

    command = [
        "ssh",

        "-i",
        str(
            ssh_identity.private_key
        ),

        "-o",
        "IdentitiesOnly=yes",

        "-o",
        "StrictHostKeyChecking=accept-new",

        "-o",
        (
            "UserKnownHostsFile="
            f"{ssh_identity.known_hosts}"
        ),

        "-o",
        "BatchMode=yes",

        "-o",
        "ConnectTimeout=5",

        f"{username}@{host}",

        "true",
    ]

    last_error = ""

    while (
        time.monotonic()
        < deadline
    ):
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode == 0:
            print(
                f"{GREEN}[✓]{RESET} "
                "SSH authentication verified."
            )

            return

        last_error = (
            result.stderr.strip()
            or result.stdout.strip()
        )

        time.sleep(
            poll_interval
        )

    raise CrucibleForgeError(
        "Crucible could reach SSH but "
        "could not authenticate using the "
        "VM's dedicated SSH identity."
        + (
            "\n\nLast SSH response:\n"
            + last_error
            if last_error
            else ""
        )
    )

def generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%^*-_"

    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))

        if (
            any(char.islower() for char in password)
            and any(char.isupper() for char in password)
            and any(char.isdigit() for char in password)
        ):
            return password


def hash_password(password: str) -> str:
    openssl = shutil.which("openssl")

    if openssl is None:
        raise CrucibleForgeError(
            "OpenSSL is required to generate the Ubuntu password hash. "
            "Install it with: sudo apt install openssl"
        )

    result = subprocess.run(
        [openssl, "passwd", "-6", "-stdin"],
        input=password + "\n",
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        raise CrucibleForgeError(
            "OpenSSL could not generate the autoinstall password hash:\n"
            + result.stderr.strip()
        )

    password_hash = result.stdout.strip()

    if not password_hash.startswith("$6$"):
        raise CrucibleForgeError(
            "OpenSSL returned an unexpected password hash format."
        )

    return password_hash


def ask_password() -> tuple[str, str]:
    print()
    print(
        "Press Enter at the password prompt to have Crucible generate "
        "a strong password."
    )

    first = getpass.getpass("Login password [generate]: ")

    if not first:
        plaintext = generate_password()
        return plaintext, hash_password(plaintext)

    second = getpass.getpass("Confirm password: ")

    if first != second:
        raise CrucibleForgeError("The two passwords did not match.")

    return first, hash_password(first)

def ask_windows_password() -> str:
    """
    Ask for a Windows local-account password.

    Pressing Enter causes Crucible to generate a strong
    password automatically.
    """

    print()
    print(
        "Press Enter at the password prompt to have "
        "Crucible generate a strong password."
    )

    first = getpass.getpass(
        "Login password [generate]: "
    )

    if not first:
        return generate_password()

    second = getpass.getpass(
        "Confirm password: "
    )

    if first != second:
        raise CrucibleForgeError(
            "The two passwords did not match."
        )

    return first

def show_autoinstall_defaults(
    vm_name: str,
    ) -> None:
    print()
    print(f"{BOLD}Autoinstall defaults:{RESET}")
    print()
    print(f"  Guest Hostname  : {vm_name}")
    print(f"  User            : {DEFAULT_AUTOINSTALL['username']}")
    print(f"  Real Name       : {DEFAULT_AUTOINSTALL['realname']}")
    print(f"  Locale          : {DEFAULT_AUTOINSTALL['locale']}")
    print(f"  Timezone        : {DEFAULT_AUTOINSTALL['timezone']}")
    print(f"  Keyboard        : {DEFAULT_AUTOINSTALL['keyboard_layout']}")
    print(f"  Storage Layout  : {DEFAULT_AUTOINSTALL['storage_layout']}")
    print(f"  Security Updates: {DEFAULT_AUTOINSTALL['updates']}")
    print("  OpenSSH Server  : yes")
    print("  SSH Password    : allowed")
    print("  Login Password  : securely generated")

    print(
    "  Crucible SSH Key: unique per-VM key"
    )
    print(
    "  SSH Key Storage : .crucible/ssh/machines/"
    )
    print()


def ask_autoinstall(
    vm_name: str,
    *,
    crucible_public_key: str,
) -> tuple[
    dict[str, Any],
    str | None,
]:
    if not crucible_public_key.strip():
        raise CrucibleForgeError(
            "Linux autoinstall requires a "
            "Crucible management public key."
        )

    authorized_keys = [
        crucible_public_key
    ]
    
    show_autoinstall_defaults(vm_name)

    use_defaults = ask_yes_no(
        f"{BOLD}Use Autoinstall Defaults?{RESET}",
        default=True,
    )

    if use_defaults:
        plaintext_password = generate_password()
        password_hash = hash_password(plaintext_password)

        return (
            {
                "enabled": True,
                "hostname": vm_name,
                "identity": {
                    "realname": DEFAULT_AUTOINSTALL["realname"],
                    "username": DEFAULT_AUTOINSTALL["username"],
                    "password_hash": password_hash,
                },
                "locale": DEFAULT_AUTOINSTALL["locale"],
                "timezone": DEFAULT_AUTOINSTALL["timezone"],
                "keyboard": {
                    "layout": DEFAULT_AUTOINSTALL["keyboard_layout"],
                    "variant": DEFAULT_AUTOINSTALL["keyboard_variant"],
                },
                "storage": {
                    "layout": DEFAULT_AUTOINSTALL["storage_layout"],
                },
                "ssh": {
                    "install_server": DEFAULT_AUTOINSTALL[
                        "ssh_install_server"
                    ],
                    "allow_password": DEFAULT_AUTOINSTALL[
                        "ssh_allow_password"
                    ],
                    "authorized_keys": authorized_keys,
                },
                "updates": DEFAULT_AUTOINSTALL["updates"],
                "shutdown": DEFAULT_AUTOINSTALL["shutdown"],
            },
            plaintext_password,
        )

    print()
    print(f"{BOLD}Custom autoinstall configuration{RESET}")
    print()

    hostname = ask_with_default("Guest Hostname", vm_name)
    username = ask_with_default(
        "Username",
        DEFAULT_AUTOINSTALL["username"],
    )
    realname = ask_with_default(
        "Real Name",
        DEFAULT_AUTOINSTALL["realname"],
    )
    locale = ask_with_default(
        "Locale",
        DEFAULT_AUTOINSTALL["locale"],
    )
    timezone = ask_with_default(
        "Timezone",
        DEFAULT_AUTOINSTALL["timezone"],
    )
    keyboard_layout = ask_with_default(
        "Keyboard Layout",
        DEFAULT_AUTOINSTALL["keyboard_layout"],
    )

    plaintext_password, password_hash = ask_password()

    install_ssh = True

    print(
        "OpenSSH Server: required by "
        "Crucible management"
    )

    allow_password = ask_yes_no(
        "Allow SSH password authentication?",
        default=True,
    )

    authorized_keys = [
        crucible_public_key
    ]

    return (
        {
            "enabled": True,
            "hostname": hostname,
            "identity": {
                "realname": realname,
                "username": username,
                "password_hash": password_hash,
            },
            "locale": locale,
            "timezone": timezone,
            "keyboard": {
                "layout": keyboard_layout,
                "variant": "",
            },
            "storage": {
                "layout": "direct",
            },
            "ssh": {
                "install_server": install_ssh,
                "allow_password": allow_password,
                "authorized_keys": authorized_keys,
            },
            "updates": "security",
            "shutdown": "reboot",
        },
        plaintext_password,
    )

def ask_windows_install_image(
    profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Resolve the Windows installation image for this machine.

    Client Windows profiles normally expose one fixed image
    selected by WIM image name.

    Windows Server profiles may expose multiple images and
    select them by WIM image index.
    """

    installer = profile.get(
        "installer",
        {},
    )

    image_choices = installer.get(
        "image_choices"
    )

    # ---------------------------------------------------------
    # Fixed-image Windows profile
    #
    # Windows 10 / Windows 11 use this path.
    # ---------------------------------------------------------

    if not image_choices:

        image_name = str(
            installer.get(
                "image_name",
                "",
            )
        ).strip()

        if not image_name:
            raise CrucibleForgeError(
                "Windows OS profile defines neither "
                "installer.image_name nor "
                "installer.image_choices."
            )

        return {
            "id": "profile-default",
            "label": image_name,
            "image_name": image_name,
            "image_index": None,
            "setup_product_key": str(
                installer.get(
                    "setup_product_key",
                    "",
                )
            ).strip(),
        }

    # ---------------------------------------------------------
    # Multi-image Windows profile
    #
    # Windows Server uses this path.
    # ---------------------------------------------------------

    if not isinstance(
        image_choices,
        list,
    ):
        raise CrucibleForgeError(
            "installer.image_choices must be a list."
        )

    normalized_choices: list[
        dict[str, Any]
    ] = []

    seen_ids: set[str] = set()

    for raw_choice in image_choices:

        if not isinstance(
            raw_choice,
            dict,
        ):
            raise CrucibleForgeError(
                "Every installer.image_choices entry "
                "must be a mapping."
            )

        choice_id = str(
            raw_choice.get(
                "id",
                "",
            )
        ).strip()

        if not choice_id:
            raise CrucibleForgeError(
                "Windows image choice has no id."
            )

        if choice_id in seen_ids:
            raise CrucibleForgeError(
                "Duplicate Windows image choice id: "
                f"{choice_id}"
            )

        seen_ids.add(
            choice_id
        )

        # -----------------------------------------------------
        # Image name is optional.
        #
        # Win10 / Win11 normally select by name.
        # Server 2022 normally selects by WIM index.
        # -----------------------------------------------------

        image_name = str(
            raw_choice.get(
                "image_name",
                "",
            )
        ).strip()

        # -----------------------------------------------------
        # Image index is optional, but when present must be
        # a positive integer.
        # -----------------------------------------------------

        image_index_raw = raw_choice.get(
            "image_index"
        )

        image_index = None

        if image_index_raw not in {
            None,
            "",
        }:

            try:
                image_index = int(
                    image_index_raw
                )

            except (
                TypeError,
                ValueError,
            ) as exc:

                raise CrucibleForgeError(
                    "Windows image choice "
                    f"{choice_id} has an invalid "
                    "image_index."
                ) from exc

            if image_index < 1:
                raise CrucibleForgeError(
                    "Windows image choice "
                    f"{choice_id} has an invalid "
                    "image_index."
                )

        # Every choice needs at least one mechanism by which
        # Windows Setup can identify its WIM image.

        if (
            image_index is None
            and
            not image_name
        ):
            raise CrucibleForgeError(
                "Windows image choice "
                f"{choice_id} defines neither "
                "image_index nor image_name."
            )

        label = str(
            raw_choice.get(
                "label",
                "",
            )
        ).strip()

        if not label:

            if image_name:
                label = image_name

            else:
                label = (
                    f"Windows image index "
                    f"{image_index}"
                )

        normalized_choices.append(
            {
                "id": choice_id,
                "label": label,
                "image_name": image_name,
                "image_index": image_index,
                "setup_product_key": str(
                    raw_choice.get(
                        "setup_product_key",
                        installer.get(
                            "setup_product_key",
                            "",
                        ),
                    )
                ).strip(),
            }
        )

    if not normalized_choices:
        raise CrucibleForgeError(
            "installer.image_choices is empty."
        )

    default_choice_id = str(
        installer.get(
            "default_image_choice",
            normalized_choices[0]["id"],
        )
    ).strip()

    default_index = None

    for index, choice in enumerate(
        normalized_choices,
        start=1,
    ):

        if (
            choice["id"]
            == default_choice_id
        ):
            default_index = index
            break

    if default_index is None:
        raise CrucibleForgeError(
            "installer.default_image_choice does "
            "not match an image_choices id: "
            f"{default_choice_id}"
        )

    print()
    print(
        f"{BOLD}"
        "Windows installation image:"
        f"{RESET}"
    )
    print()

    for index, choice in enumerate(
        normalized_choices,
        start=1,
    ):

        default_marker = (
            " [default]"
            if index == default_index
            else ""
        )

        print(
            f"  [{index}] "
            f"{choice['label']}"
            f"{default_marker}"
        )

    print()

    while True:

        answer = input(
            f"Selection [{default_index}]: "
        ).strip()

        if not answer:
            selected_index = (
                default_index
            )

        else:

            try:
                selected_index = int(
                    answer
                )

            except ValueError:
                print(
                    f"{RED}"
                    "Enter one of the listed numbers."
                    f"{RESET}"
                )
                continue

        if (
            1
            <= selected_index
            <= len(normalized_choices)
        ):
            return dict(
                normalized_choices[
                    selected_index - 1
                ]
            )

        print(
            f"{RED}"
            "Enter one of the listed numbers."
            f"{RESET}"
        )

def show_windows_unattend_defaults(
    *,
    vm_name: str,
    edition: str,
) -> None:
    """
    Display the effective Windows unattended-install
    defaults before allowing the user to customize them.
    """

    print()
    print(
        f"{BOLD}"
        "Windows unattended-install defaults:"
        f"{RESET}"
    )
    print()

    print(
        f"  Computer Name     : "
        f"{vm_name}"
    )

    print(
        f"  Edition           : "
        f"{edition}"
    )

    print(
        f"  User              : "
        f"{DEFAULT_WINDOWS_UNATTEND['username']}"
    )

    print(
        f"  Display Name      : "
        f"{DEFAULT_WINDOWS_UNATTEND['realname']}"
    )

    print(
        f"  UI Language       : "
        f"{DEFAULT_WINDOWS_UNATTEND['ui_language']}"
    )

    print(
        f"  Input Locale      : "
        f"{DEFAULT_WINDOWS_UNATTEND['input_locale']}"
    )

    print(
        f"  System Locale     : "
        f"{DEFAULT_WINDOWS_UNATTEND['system_locale']}"
    )

    print(
        f"  User Locale       : "
        f"{DEFAULT_WINDOWS_UNATTEND['user_locale']}"
    )

    print(
        f"  Timezone          : "
        f"{DEFAULT_WINDOWS_UNATTEND['timezone']}"
    )

    print(
        f"  Organization      : "
        f"{DEFAULT_WINDOWS_UNATTEND['organization']}"
    )

    print(
        "  Login Password    : securely generated"
    )

    print(
        "  Disk              : wipe Disk 0"
    )

    print(
        "  Partitioning      : GPT / EFI / MSR / Windows"
    )

    print(
        "  Account Type      : local administrator"
    )

    print(
        "  First Login       : automatic once"
    )

    print()

def ask_windows_unattend(
    os_info: dict[str, Any],
    vm_name: str,
) -> tuple[dict[str, Any], str]:
    """
    Build Windows unattended-install settings.

    The user may accept Crucible's defaults or customize
    machine-specific identity and regional settings.

    The available Windows installation images are controlled
    by the OS profile. Profiles with multiple images allow the
    Forge to select the desired edition / installation mode.

    Disk layout, administrator membership and the single
    bootstrap autologon remain controlled by Crucible.
    """

    profile = load_os_profile(
        str(
            os_info[
                "profile"
            ]
        )
    )

    installer = profile.get(
        "installer",
        {},
    )

    install_image = (
        ask_windows_install_image(
            profile
        )
    )

    edition = str(
        install_image[
            "label"
        ]
    ).strip()

    show_windows_unattend_defaults(
        vm_name=vm_name,
        edition=edition,
    )

    use_defaults = ask_yes_no(
        f"{BOLD}"
        "Use Windows unattended-install defaults?"
        f"{RESET}",
        default=True,
    )

    if use_defaults:

        plaintext_password = (
            generate_password()
        )

        validate_windows_computer_name(vm_name)

        return (
            {
                "enabled": True,

                "hostname": vm_name,

                "install_image": {
                    "id": (
                        install_image[
                            "id"
                        ]
                    ),

                    "label": (
                        install_image[
                            "label"
                        ]
                    ),

                    "index": (
                        install_image[
                            "image_index"
                        ]
                    ),

                    "name": (
                        install_image[
                            "image_name"
                        ]
                    ),

                    "setup_product_key": (
                        install_image[
                            "setup_product_key"
                        ]
                    ),
                },

                "identity": {
                    "realname": (
                        DEFAULT_WINDOWS_UNATTEND[
                            "realname"
                        ]
                    ),

                    "username": (
                        DEFAULT_WINDOWS_UNATTEND[
                            "username"
                        ]
                    ),

                    "password": (
                        plaintext_password
                    ),
                },

                "locale": {
                    "ui_language": (
                        DEFAULT_WINDOWS_UNATTEND[
                            "ui_language"
                        ]
                    ),

                    "input_locale": (
                        DEFAULT_WINDOWS_UNATTEND[
                            "input_locale"
                        ]
                    ),

                    "system_locale": (
                        DEFAULT_WINDOWS_UNATTEND[
                            "system_locale"
                        ]
                    ),

                    "user_locale": (
                        DEFAULT_WINDOWS_UNATTEND[
                            "user_locale"
                        ]
                    ),
                },

                "timezone": (
                    DEFAULT_WINDOWS_UNATTEND[
                        "timezone"
                    ]
                ),

                "organization": (
                    DEFAULT_WINDOWS_UNATTEND[
                        "organization"
                    ]
                ),

                "disk": {
                    "id": 0,
                },

                "autologon": {
                    "enabled": True,
                    "count": 1,
                },
            },

            plaintext_password,
        )


    # ---------------------------------------------------------
    # Custom Windows unattended-install configuration
    # ---------------------------------------------------------

    print()
    print(
        f"{BOLD}"
        "Custom Windows unattended-install configuration"
        f"{RESET}"
    )
    print()

    while True:
        hostname = ask_with_default(
            "Computer Name",
            vm_name,
        )

        try:
            validate_windows_computer_name(hostname)
            break
        except CrucibleForgeError as exc:
            print(f"{RED}{exc}{RESET}")

    username = ask_with_default(
        "Username",
        DEFAULT_WINDOWS_UNATTEND[
            "username"
        ],
    )

    realname = ask_with_default(
        "Display Name",
        DEFAULT_WINDOWS_UNATTEND[
            "realname"
        ],
    )

    ui_language = ask_with_default(
        "UI Language",
        DEFAULT_WINDOWS_UNATTEND[
            "ui_language"
        ],
    )

    input_locale = ask_with_default(
        "Input Locale",
        DEFAULT_WINDOWS_UNATTEND[
            "input_locale"
        ],
    )

    system_locale = ask_with_default(
        "System Locale",
        DEFAULT_WINDOWS_UNATTEND[
            "system_locale"
        ],
    )

    user_locale = ask_with_default(
        "User Locale",
        DEFAULT_WINDOWS_UNATTEND[
            "user_locale"
        ],
    )

    timezone = ask_with_default(
        "Timezone",
        DEFAULT_WINDOWS_UNATTEND[
            "timezone"
        ],
    )

    organization = ask_with_default(
        "Organization",
        DEFAULT_WINDOWS_UNATTEND[
            "organization"
        ],
    )

    plaintext_password = (
        ask_windows_password()
    )

    print(
        f"{DIM}"
        f"Windows installation image: "
        f"{edition}"
        f"{RESET}"
    )

    print(
        f"{DIM}"
        "Disk 0 will be wiped and the Crucible "
        "administrator will automatically log in once "
        "so bootstrap.ps1 can run."
        f"{RESET}"
    )

    return (
        {
            "enabled": True,

            "hostname": hostname,

            "install_image": {
                "id": (
                    install_image[
                        "id"
                    ]
                ),

                "label": (
                    install_image[
                        "label"
                    ]
                ),

                "index": (
                    install_image[
                        "image_index"
                    ]
                ),

                "name": (
                    install_image[
                        "image_name"
                    ]
                ),

                "setup_product_key": (
                    install_image[
                        "setup_product_key"
                    ]
                ),
            },

            "identity": {
                "realname": realname,
                "username": username,
                "password": (
                    plaintext_password
                ),
            },

            "locale": {
                "ui_language": (
                    ui_language
                ),

                "input_locale": (
                    input_locale
                ),

                "system_locale": (
                    system_locale
                ),

                "user_locale": (
                    user_locale
                ),
            },

            "timezone": timezone,

            "organization": organization,

            "disk": {
                "id": 0,
            },

            "autologon": {
                "enabled": True,
                "count": 1,
            },
        },

        plaintext_password,
    )

def ask_installation_configuration(
    os_info: dict[str, Any],
    vm_name: str,
    *,
    crucible_public_key: str | None = None,
):
    """
    Dispatch installation configuration according to the
    selected OS profile and installer backend.

    Linux and Windows installers expose their normal
    Crucible defaults and allow machine-specific
    customization where appropriate.
    """

    profile = load_os_profile(
        str(os_info["profile"])
    )

    installer = profile.get(
        "installer",
        {},
    )

    backend = str(
        installer.get(
            "backend",
            "",
        )
    ).strip().lower()

    if backend in {
        "ubuntu-autoinstall",
        "debian-preseed",
    }:
        if not crucible_public_key:
            raise CrucibleForgeError(
                "Linux installation requires "
                "a Crucible SSH identity."
            )

        return ask_autoinstall(
            vm_name,
            crucible_public_key=(
                crucible_public_key
            ),
        )

    if backend == "windows-unattend":
        return ask_windows_unattend(
            os_info,
            vm_name,
        )

    raise CrucibleForgeError(
        "Unsupported installer backend: "
        f"{backend or 'undefined'}"
    )

def build_machine_manifest(
    os_info: dict[str, Any],
    machine_name: str,
    hardware: dict[str, Any],
    autoinstall: dict[str, Any],
    management_address: str,
    instance_serial: str,
) -> dict[str, Any]:

    profile = load_os_profile(
        str(os_info["profile"])
    )

    installer = profile.get(
        "installer",
        {},
    )

    resolved_autoinstall = dict(
        autoinstall
    )

    source_id = installer.get(
        "source_id"
    )

    if source_id:
        resolved_autoinstall[
            "source_id"
        ] = str(source_id)

    topology_interfaces = list(
        hardware.get(
            "topology_interfaces",
            [],
        )
    )

    network_layout = (
        build_network_slot_layout(
            len(
                topology_interfaces
            ),
            internet_enabled=True,
            management_enabled=True,
        )
    )

    resolved_topology: list[
        dict[str, Any]
    ] = []

    for interface, slot in zip(
        topology_interfaces,
        network_layout.topology_slots,
    ):
        resolved_interface = dict(
            interface
        )

        resolved_interface[
            "slot"
        ] = slot

        resolved_interface[
            "mac_address"
        ] = (
            topology_mac_for_machine(
                machine_name,
                slot,
            )
        )

        resolved_topology.append(
            resolved_interface
        )

    return {
        "instance": {
            "serial": (
                instance_serial
            ),
        },
        "schema_version": 2,
        "name": machine_name,
        "profile": os_info["profile"],
        "image_id": os_info["image_id"],
        "resources": {
            "cpus": hardware["cpus"],
            "memory_mb": hardware["memory_mb"],
            "disk_gb": hardware["disk_gb"],
        },

        "virtualbox": {
            "firmware": hardware["firmware"],
            "graphics": {
                "controller": hardware[
                    "graphics_controller"
                ],
                "vram_mb": hardware["vram_mb"],
                "accelerate_3d": hardware[
                    "accelerate_3d"
                ],
            },
        },
        "network": {
            "topology": (
                resolved_topology
            ),

            "internet": {
                "enabled": True,
                "slot": (
                    network_layout
                    .internet_slot
                ),
                "mode": "nat",
                "mac_address": (
                    internet_mac_for_machine(
                        machine_name
                    )
                ),
            },

            "management": {
                "enabled": True,
                "slot": (
                    network_layout
                    .management_slot
                ),
                "address": (
                    management_address
                ),
                "mac_address": (
                    management_mac_for_machine(
                        machine_name
                    )
                ),
            },
        },
        "autoinstall": resolved_autoinstall,
        "start": {
            "enabled": True,
            "headless": False,
        },
    }


def build_lab_manifest(
    machine_manifest_path: Path,
    machine_name: str,
    instance_serial: str,
) -> dict[str, Any]:
    relative_machine_path = (
        machine_manifest_path.relative_to(REPO_ROOT).as_posix()
    )

    return {
        "schema_version": 2,
        "name": "crucible-lab",
        "machines": [
            {
                "name": machine_name,
                "manifest": relative_machine_path,
            }
        ],
    }


def write_yaml(
    path: Path,
    data: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            data,
            file,
            sort_keys=False,
            default_flow_style=False,
        )

def generate_manifests(
    os_info: dict[str, Any],
    machine_name: str,
    hardware: dict[str, Any],
    autoinstall: dict[str, Any],
    instance_serial: str,
) -> tuple[Path, Path]:

    management_address = (
        allocate_management_address(
            machine_name
        )
    )

    machine_path = (
        MACHINE_MANIFEST_DIR
        / f"{machine_name}.yml"
    )

    lab_path = (
        LAB_MANIFEST_DIR
        / "crucible-lab.yml"
    )

    machine_manifest = (
        build_machine_manifest(
            os_info,
            machine_name,
            hardware,
            autoinstall,
            management_address,
            instance_serial,
        )
    )

    write_yaml(
        machine_path,
        machine_manifest,
    )

    lab_manifest = build_lab_manifest(
        machine_path,
        machine_name,
        instance_serial,
    )

    write_yaml(
        lab_path,
        lab_manifest,
    )

    return (
        lab_path,
        machine_path,
    )

def get_machine_connection_info(
    machine_manifest_path: Path,
) -> tuple[str, str, str]:
    """
    Extract the information Crucible needs to reach the newly
    created machine.
    """

    with machine_manifest_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        manifest = yaml.safe_load(file)

    machine_name = str(
        manifest["name"]
    )

    username = str(
        manifest["autoinstall"]
        ["identity"]
        ["username"]
    )

    management_address = str(
        manifest["network"]
        ["management"]
        ["address"]
    )

    # Convert a CIDR management address such as:
    #
    # 172.31.0.2/16
    #
    # into:
    #
    # 172.31.0.2

    management_ip = management_address.split(
        "/",
        1,
    )[0]

    return (
        machine_name,
        management_ip,
        username,
    )

def get_windows_connection_info(
    machine_manifest_path: Path,
) -> dict[str, Any]:
    """
    Extract controller-side Windows management information
    from the generated runtime manifest and OS profile.
    """

    with machine_manifest_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        manifest = yaml.safe_load(
            file
        )

    if not isinstance(
        manifest,
        dict,
    ):
        raise CrucibleForgeError(
            "Windows machine manifest is not valid YAML."
        )

    profile_name = str(
        manifest.get(
            "profile",
            "",
        )
    ).strip()

    if not profile_name:
        raise CrucibleForgeError(
            "Windows machine manifest has no profile."
        )

    profile = load_os_profile(
        profile_name
    )

    management_profile = profile.get(
        "management",
        {},
    )

    transport = str(
        management_profile.get(
            "transport",
            "",
        )
    ).strip().lower()

    if transport != "psrp":
        raise CrucibleForgeError(
            "Windows management currently requires "
            f"PSRP; profile specifies "
            f"{transport or 'nothing'}."
        )

    autoinstall = manifest.get(
        "autoinstall",
        {},
    )

    identity = autoinstall.get(
        "identity",
        {},
    )

    username = str(
        identity.get(
            "username",
            management_profile.get(
                "user",
                "",
            ),
        )
    ).strip()

    password = str(
        identity.get(
            "password",
            "",
        )
    )

    if not username:
        raise CrucibleForgeError(
            "Windows runtime manifest does not "
            "contain a management username."
        )

    if not password:
        raise CrucibleForgeError(
            "Windows runtime manifest does not "
            "contain the generated management password."
        )

    network = manifest.get(
        "network",
        {},
    )

    management_network = network.get(
        "management",
        {},
    )

    management_address = str(
        management_network.get(
            "address",
            "",
        )
    ).strip()

    if not management_address:
        raise CrucibleForgeError(
            "Windows runtime manifest does not "
            "contain a management address."
        )

    management_ip = (
        management_address.split(
            "/",
            1,
        )[0]
    )

    readiness = management_profile.get(
        "readiness",
        {},
    )

    return {
        "machine_name": str(
            manifest["name"]
        ),

        "management_ip": (
            management_ip
        ),

        "username": username,

        "password": password,

        "transport": transport,

        "protocol": str(
            management_profile.get(
                "protocol",
                "https",
            )
        ).strip().lower(),

        "port": int(
            management_profile.get(
                "port",
                5986,
            )
        ),

        "auth": str(
            management_profile.get(
                "auth",
                "ntlm",
            )
        ).strip().lower(),

        "cert_validation": str(
            management_profile.get(
                "cert_validation",
                "ignore",
            )
        ).strip().lower(),

        "port_timeout_seconds": int(
            readiness.get(
                "port_timeout_seconds",
                3600,
            )
        ),

        "connection_timeout_seconds": int(
            readiness.get(
                "connection_timeout_seconds",
                900,
            )
        ),

        "bootstrap_timeout_seconds": int(
            readiness.get(
                "bootstrap_timeout_seconds",
                600,
            )
        ),

        "poll_interval_seconds": float(
            readiness.get(
                "poll_interval_seconds",
                5,
            )
        ),
    }

def wait_for_tcp_port(
    host: str,
    *,
    port: int,
    service_name: str,
    timeout: int,
    poll_interval: float = 3.0,
) -> None:
    """
    Wait until a TCP service begins accepting connections.
    """

    print()
    print(
        f"{CYAN}Waiting for "
        f"{service_name} on "
        f"{host}:{port}..."
        f"{RESET}"
    )

    deadline = (
        time.monotonic()
        + timeout
    )

    while (
        time.monotonic()
        < deadline
    ):
        try:

            with socket.create_connection(
                (
                    host,
                    port,
                ),
                timeout=2.0,
            ):

                print(
                    f"{GREEN}[✓]{RESET} "
                    f"{service_name} port "
                    f"is reachable."
                )

                return

        except OSError:

            time.sleep(
                poll_interval
            )

    raise CrucibleForgeError(
        f"Timed out waiting for "
        f"{service_name} on "
        f"{host}:{port}."
    )


def wait_for_ssh(
    host: str,
    *,
    port: int = 22,
    timeout: int = 3000,
    poll_interval: float = 3.0,
) -> None:
    """
    Linux compatibility wrapper around the generic
    TCP-service readiness check.
    """

    wait_for_tcp_port(
        host,
        port=port,
        service_name="SSH",
        timeout=timeout,
        poll_interval=poll_interval,
    )

def forge_machine(
    machine_manifest_path: Path,
) -> None:
    print()
    print(
        f"{GOLD}{BOLD}"
        "=========================================="
        f"{RESET}"
    )
    print(
        f"{GOLD}{BOLD}"
        "              FORGING VM"
        f"{RESET}"
    )
    print(
        f"{GOLD}{BOLD}"
        "=========================================="
        f"{RESET}"
    )
    print()

    create_machine(
        machine_manifest_path,
        verbose=False,
    )

def generate_ansible_inventory(
    *,
    machine_name: str,
    host: str,
    username: str,
    ssh_identity: SshIdentity,
) -> Path:
    """
    Generate Crucible's runtime Ansible inventory.
    """

    inventory_path = (
        ANSIBLE_RUNTIME_DIR
        / "inventory.yml"
    )

    inventory_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    inventory = {
        "all": {
            "hosts": {
                machine_name: {
                    "ansible_host": host,

                    "ansible_user": username,

                    "ansible_ssh_private_key_file": (
                        str(
                            ssh_identity.private_key
                        )
                    ),

                    "ansible_ssh_common_args": (
                        "-o IdentitiesOnly=yes "
                        "-o StrictHostKeyChecking=accept-new "
                        "-o UserKnownHostsFile="
                        f"{ssh_identity.known_hosts}"
                    ),

                    "ansible_python_interpreter": (
                        "/usr/bin/python3"
                    ),
                }
            }
        }
    }

    with inventory_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            inventory,
            file,
            sort_keys=False,
        )

    return inventory_path

def generate_windows_ansible_inventory(
    *,
    machine_name: str,
    host: str,
    username: str,
    password: str,
    protocol: str,
    port: int,
    auth: str,
    cert_validation: str,
) -> Path:
    """
    Generate Crucible's runtime Ansible inventory for a
    Windows machine managed through PSRP.

    This inventory contains the generated Windows password,
    so it remains exclusively under .crucible/.
    """

    inventory_path = (
        ANSIBLE_RUNTIME_DIR
        / "inventory.yml"
    )

    inventory_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    inventory = {
        "all": {
            "hosts": {
                machine_name: {

                    "ansible_host": (
                        host
                    ),

                    "ansible_connection": (
                        "psrp"
                    ),

                    "ansible_user": (
                        username
                    ),

                    "ansible_password": (
                        password
                    ),

                    "ansible_psrp_protocol": (
                        protocol
                    ),

                    "ansible_psrp_port": (
                        port
                    ),

                    "ansible_psrp_auth": (
                        auth
                    ),

                    "ansible_psrp_cert_validation": (
                        cert_validation
                    ),

                    # This is an isolated host-only
                    # management network. Do not let
                    # controller proxy environment settings
                    # interfere with the direct connection.
                    "ansible_psrp_ignore_proxy": (
                        True
                    ),
                }
            }
        }
    }

    with inventory_path.open(
        "w",
        encoding="utf-8",
    ) as file:

        yaml.safe_dump(
            inventory,
            file,
            sort_keys=False,
        )

    # The Windows runtime inventory contains the plaintext
    # generated local-administrator password.
    inventory_path.chmod(
        0o600
    )

    return inventory_path

def wait_for_bootstrap(
    *,
    host: str,
    username: str,
    ssh_identity: SshIdentity,
    timeout: int = 3000,
    poll_interval: float = 5.0,
) -> None:
    """
    Wait for the installed Linux guest to expose Crucible's
    bootstrap-complete marker.

    Host-key persistence is deliberately disabled during this
    transitional phase because the installer environment may
    reboot into a final system with newly-generated SSH host keys.
    """

    print()
    print(
        f"{CYAN}"
        "Waiting for Crucible bootstrap "
        f"to complete..."
        f"{RESET}"
    )

    deadline = (
        time.monotonic()
        + timeout
    )

    command = [
        "ssh",

        "-i",
        str(
            ssh_identity.private_key
        ),

        "-o",
        "IdentitiesOnly=yes",

        # Transitional installation phase:
        # do not pin an SSH host identity yet.
        "-o",
        "StrictHostKeyChecking=no",

        "-o",
        "UserKnownHostsFile=/dev/null",

        "-o",
        "BatchMode=yes",

        "-o",
        "ConnectTimeout=5",

        "-o",
        "LogLevel=ERROR",

        f"{username}@{host}",

        (
            "test -f "
            "/var/lib/crucible/"
            "bootstrap-complete"
        ),
    ]

    last_error = ""

    while (
        time.monotonic()
        < deadline
    ):
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode == 0:
            print(
                f"{GREEN}[✓]{RESET} "
                "Bootstrap complete."
            )

            return

        last_error = (
            result.stderr.strip()
            or
            result.stdout.strip()
        )

        time.sleep(
            poll_interval
        )

    details = ""

    if last_error:
        details = (
            "\n\nLast SSH response:\n"
            + last_error
        )

    raise CrucibleForgeError(
        "Timed out waiting for Linux "
        "bootstrap to complete."
        + details
    )

def verify_ansible(
    *,
    machine_name: str,
    inventory_path: Path,
) -> None:
    """
    Perform Crucible's final Ansible connectivity test.
    """

    print()
    print(
        f"{CYAN}Verifying Ansible connectivity...{RESET}"
    )
    print()

    result = subprocess.run(
        [
            "ansible",
            machine_name,
            "-i",
            str(inventory_path),
            "-m",
            "ansible.builtin.ping",
        ],
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise CrucibleForgeError(
            "Ansible connectivity verification failed."
        )

    print()
    print(
        f"{GREEN}[✓]{RESET} "
        f"Ansible connectivity verified."
    )

def verify_linux_machine_ready(
    machine_manifest_path: Path,
) -> None:
    """
    Wait for a newly forged machine to become completely
    manageable by Crucible.
    """

    if shutil.which("ansible") is None:
        raise CrucibleForgeError(
            "Ansible was not found on the controller. "
            "Install it before forging machines."
        )

    (
        machine_name,
        management_ip,
        username,
    ) = get_machine_connection_info(
        machine_manifest_path
    )

    instance_serial = (
        get_machine_instance_serial(
            machine_manifest_path
        )
    )

    ssh_identity = (
        load_machine_ssh_identity(
            repo_root=REPO_ROOT,
            machine_name=machine_name,
            instance_serial=instance_serial,
        )
    )

    print()
    print(
        f"{BOLD}Management target:{RESET} "
        f"{username}@{management_ip}"
    )

    # 1. Something is listening on TCP/22.
    wait_for_ssh(
        management_ip
    )

    # 2. Wait through installer/final-OS transitions without
    #    committing a host key to permanent trust.
    wait_for_bootstrap(
        host=management_ip,
        username=username,
        ssh_identity=ssh_identity,
    )

    # 3. We now know the installed OS is running.
    #    Establish its permanent SSH host identity.
    reset_machine_known_hosts(
        ssh_identity
    )

    wait_for_ssh_authentication(
        host=management_ip,
        username=username,
        ssh_identity=ssh_identity,
    )

    # 4. Generate Ansible inventory only after final SSH
    #    trust has been established.
    inventory_path = (
        generate_ansible_inventory(
            machine_name=machine_name,
            host=management_ip,
            username=username,
            ssh_identity=ssh_identity,
        )
    )

    print(
        "\n\n\n"
        f"{GREEN}[✓]{RESET} "
        "Ansible inventory generated:"
    )
    print(
        "    "
        f"{inventory_path.relative_to(REPO_ROOT)}"
    )

    # 5. Everything from here onward uses the permanent
    #    per-instance SSH identity/trust database.
    verify_ansible(
        machine_name=machine_name,
        inventory_path=inventory_path,
    )

def verify_windows_machine_ready(
    machine_manifest_path: Path,
) -> None:
    """
    Wait for a newly forged Windows machine to become
    completely manageable by Crucible through PSRP.
    """

    verify_windows_ansible_prerequisites()

    connection = (
        get_windows_connection_info(
            machine_manifest_path
        )
    )

    machine_name = str(
        connection[
            "machine_name"
        ]
    )

    management_ip = str(
        connection[
            "management_ip"
        ]
    )

    username = str(
        connection[
            "username"
        ]
    )

    print()
    print(
        f"{BOLD}Management target:{RESET} "
        f"{username}@{management_ip} "
        f"via PSRP/"
        f"{connection['protocol'].upper()}:"
        f"{connection['port']}"
    )

    inventory_path = (
        generate_windows_ansible_inventory(
            machine_name=machine_name,
            host=management_ip,
            username=username,
            password=str(
                connection[
                    "password"
                ]
            ),
            protocol=str(
                connection[
                    "protocol"
                ]
            ),
            port=int(
                connection[
                    "port"
                ]
            ),
            auth=str(
                connection[
                    "auth"
                ]
            ),
            cert_validation=str(
                connection[
                    "cert_validation"
                ]
            ),
        )
    )

    print(
        f"{GREEN}[✓]{RESET} "
        "Windows Ansible inventory generated:"
    )

    print(
        "    "
        f"{inventory_path.relative_to(REPO_ROOT)}"
    )

    print(
        f"{DIM}"
        "    Runtime inventory contains the "
        "generated Windows password and is "
        "mode 0600 under .crucible/."
        f"{RESET}"
    )

    wait_for_tcp_port(
        management_ip,
        port=int(
            connection[
                "port"
            ]
        ),
        service_name="WinRM HTTPS",
        timeout=int(
            connection[
                "port_timeout_seconds"
            ]
        ),
        poll_interval=float(
            connection[
                "poll_interval_seconds"
            ]
        ),
    )

    wait_for_windows_psrp(
        machine_name=machine_name,
        inventory_path=inventory_path,
        timeout=int(
            connection[
                "connection_timeout_seconds"
            ]
        ),
        poll_interval=float(
            connection[
                "poll_interval_seconds"
            ]
        ),
    )

    wait_for_windows_bootstrap(
        machine_name=machine_name,
        inventory_path=inventory_path,
        timeout=int(
            connection[
                "bootstrap_timeout_seconds"
            ]
        ),
        poll_interval=float(
            connection[
                "poll_interval_seconds"
            ]
        ),
    )

    verify_windows_ansible(
        machine_name=machine_name,
        inventory_path=inventory_path,
    )

def verify_machine_ready(
    machine_manifest_path: Path,
) -> None:
    """
    Dispatch controller-side readiness verification according
    to the guest operating-system family.
    """

    with machine_manifest_path.open(
        "r",
        encoding="utf-8",
    ) as file:

        manifest = yaml.safe_load(
            file
        )

    if not isinstance(
        manifest,
        dict,
    ):
        raise CrucibleForgeError(
            "Machine manifest is not valid YAML."
        )

    profile_name = str(
        manifest.get(
            "profile",
            "",
        )
    ).strip()

    if not profile_name:
        raise CrucibleForgeError(
            "Machine manifest has no OS profile."
        )

    profile = load_os_profile(
        profile_name
    )

    guest_family = str(
        profile.get(
            "os",
            {},
        ).get(
            "family",
            "",
        )
    ).strip().lower()

    if guest_family == "linux":

        verify_linux_machine_ready(
            machine_manifest_path
        )

        return

    if guest_family == "windows":

        verify_windows_machine_ready(
            machine_manifest_path
        )

        return

    raise CrucibleForgeError(
        "No readiness verification path exists "
        "for guest family: "
        f"{guest_family or 'undefined'}"
    )

def verify_windows_ansible_prerequisites() -> None:
    """
    Verify the controller has the Ansible pieces required
    for Windows PSRP management.
    """

    if shutil.which(
        "ansible"
    ) is None:

        raise CrucibleForgeError(
            "Ansible was not found on the controller."
        )

    ansible_doc = shutil.which(
        "ansible-doc"
    )

    if ansible_doc is None:

        raise CrucibleForgeError(
            "ansible-doc was not found on the controller."
        )

    result = subprocess.run(
        [
            ansible_doc,
            "-t",
            "module",
            "ansible.windows.win_ping",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:

        raise CrucibleForgeError(
            "The ansible.windows collection is not "
            "available on the controller. Install the "
            "repository's Ansible requirements with:\n"
            "  ansible-galaxy collection install "
            "-r ansible/requirements.yml"
        )

def ask_int_with_default(
    prompt: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    while True:
        answer = input(
            f"{prompt} [{default}]: "
        ).strip()

        if not answer:
            return default

        try:
            value = int(answer)
        except ValueError:
            print(
                f"{RED}Please enter a whole number.{RESET}"
            )
            continue

        if value < minimum or value > maximum:
            print(
                f"{RED}Value must be between "
                f"{minimum} and {maximum}.{RESET}"
            )
            continue

        return value

def ask_choice(
    prompt: str,
    default: str,
    choices: set[str],
) -> str:
    choices_text = "/".join(
        sorted(choices)
    )

    while True:
        answer = input(
            f"{prompt} [{default}] "
            f"({choices_text}): "
        ).strip().lower()

        if not answer:
            return default

        if answer in choices:
            return answer

        print(
            f"{RED}Choose one of: "
            f"{choices_text}.{RESET}"
        )

def wait_for_windows_psrp(
    *,
    machine_name: str,
    inventory_path: Path,
    timeout: int,
    poll_interval: float,
) -> None:
    """
    Wait until Ansible can establish a complete usable PSRP
    session with the Windows guest.

    ansible.builtin.wait_for_connection automatically uses
    the target's configured connection plugin and Windows
    ping implementation.
    """

    print()
    print(
        f"{CYAN}"
        "Waiting for Windows PSRP management "
        "to become usable..."
        f"{RESET}"
    )

    sleep_seconds = max(
        1,
        int(
            poll_interval
        ),
    )

    result = subprocess.run(
        [
            "ansible",
            machine_name,
            "-i",
            str(
                inventory_path
            ),
            "-m",
            (
                "ansible.builtin."
                "wait_for_connection"
            ),
            "-a",
            (
                f"timeout={timeout} "
                "connect_timeout=10 "
                f"sleep={sleep_seconds}"
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:

        details = (
            result.stdout.strip()
            or
            result.stderr.strip()
            or
            "No Ansible diagnostic output."
        )

        raise CrucibleForgeError(
            "Windows PSRP did not become usable.\n"
            f"{details}"
        )

    print(
        f"{GREEN}[✓]{RESET} "
        "Windows PSRP connection is usable."
    )

def wait_for_windows_bootstrap(
    *,
    machine_name: str,
    inventory_path: Path,
    timeout: int,
    poll_interval: float = 5.0,
) -> None:
    """
    Wait until bootstrap.ps1 reports completion.

    If bootstrap.ps1 created bootstrap-failed, surface that
    failure immediately instead of waiting for the full
    timeout.
    """

    print()
    print(
        f"{CYAN}"
        "Waiting for Crucible Windows bootstrap "
        "to complete..."
        f"{RESET}"
    )

    deadline = (
        time.monotonic()
        + timeout
    )

    failed_path = (
        WINDOWS_BOOTSTRAP_FAILED_PATH
    )

    complete_path = (
        WINDOWS_BOOTSTRAP_COMPLETE_PATH
    )

    probe_script = (
        f"$failed = '{failed_path}'; "
        f"$complete = '{complete_path}'; "

        "if (Test-Path $failed) { "
        "Write-Output "
        "'CRUCIBLE_BOOTSTRAP_FAILED'; "
        "Get-Content $failed -Raw; "
        "exit 2 "
        "}; "

        "if (Test-Path $complete) { "
        "Write-Output "
        "'CRUCIBLE_BOOTSTRAP_COMPLETE'; "
        "exit 0 "
        "}; "

        "exit 1"
    )

    command = [
        "ansible",
        machine_name,
        "-i",
        str(
            inventory_path
        ),
        "-m",
        "ansible.windows.win_shell",
        "-a",
        probe_script,
    ]

    while (
        time.monotonic()
        < deadline
    ):

        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        combined_output = (
            result.stdout
            + "\n"
            + result.stderr
        )

        if (
            "CRUCIBLE_BOOTSTRAP_FAILED"
            in combined_output
        ):

            raise CrucibleForgeError(
                "Windows bootstrap reported failure:\n"
                + combined_output.strip()
            )

        if (
            result.returncode == 0
            and
            "CRUCIBLE_BOOTSTRAP_COMPLETE"
            in combined_output
        ):

            print(
                f"{GREEN}[✓]{RESET} "
                "Windows bootstrap complete."
            )

            return

        time.sleep(
            poll_interval
        )

    raise CrucibleForgeError(
        "Timed out waiting for Windows "
        "bootstrap to complete."
    )

def verify_windows_ansible(
    *,
    machine_name: str,
    inventory_path: Path,
) -> None:
    """
    Perform Crucible's final Windows Ansible connectivity
    verification.
    """

    print()
    print(
        f"{CYAN}"
        "Verifying Windows Ansible connectivity..."
        f"{RESET}"
    )
    print()

    result = subprocess.run(
        [
            "ansible",
            machine_name,
            "-i",
            str(
                inventory_path
            ),
            "-m",
            "ansible.windows.win_ping",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.stdout:
        print(
            result.stdout.rstrip()
        )

    if result.stderr:
        print(
            result.stderr.rstrip(),
            file=sys.stderr,
        )

    if result.returncode != 0:

        raise CrucibleForgeError(
            "Windows Ansible connectivity "
            "verification failed."
        )

    if "pong" not in result.stdout:

        raise CrucibleForgeError(
            "Windows Ansible command returned success "
            "but did not return the expected pong."
        )

    print()
    print(
        f"{GREEN}[✓]{RESET} "
        "Windows Ansible connectivity verified."
    )

def main() -> int:
    try:
        show_banner()

        vm_count = ask_vm_count()

        if vm_count != SUPPORTED_VM_COUNT:
            raise CrucibleForgeError(
                "Unsupported VM count reached "
                "orchestration layer."
            )

        os_info = ask_operating_system()

        vm_name = ask_vm_name(
            os_info
        )

        instance_serial = (
            generate_instance_serial()
        )

        guest_family = (
            get_guest_family(
                os_info
            )
        )

        ssh_identity: (
            SshIdentity | None
        ) = None

        if guest_family == "linux":
            ssh_identity = (
                create_machine_ssh_identity(
                    repo_root=REPO_ROOT,
                    machine_name=vm_name,
                    instance_serial=(
                        instance_serial
                    ),
                )
            )

            print()
            print(
                f"{GREEN}[✓]{RESET} "
                "Crucible SSH identity created."
            )

            print(
                f"  Instance serial : "
                f"{instance_serial}"
            )

            print(
                f"  SSH identity    : "
                f"{ssh_identity.directory.relative_to(REPO_ROOT)}"
            )

        hardware = ask_hardware_defaults(
            os_info
        )

        topology_interfaces = (
            ask_topology_interfaces()
        )

        hardware[
            "topology_interfaces"
        ] = topology_interfaces

        show_network_slot_plan(
            topology_interfaces
        )

        autoinstall, plaintext_password = (
            ask_installation_configuration(
                os_info,
                vm_name,
                crucible_public_key=(
                    ssh_identity.public_key_text
                    if ssh_identity
                    else None
                ),
            )
        )

        print()
        print(f"{CYAN}Generating Crucible manifests...{RESET}")

        lab_path, machine_path = (
            generate_manifests(
                os_info,
                vm_name,
                hardware,
                autoinstall,
                instance_serial,
            )
        )

        print()
        print(f"{GREEN}[✓]{RESET} Topology manifest:")
        print(f"    {lab_path.relative_to(REPO_ROOT)}")

        print()
        print(f"{GREEN}[✓]{RESET} Machine manifest:")
        print(f"    {machine_path.relative_to(REPO_ROOT)}")

        if plaintext_password:
            print()
            print(
                f"{YELLOW}{BOLD}"
                "Generated login credentials"
                f"{RESET}"
            )

            print(
                f"  Username: "
                f"{autoinstall['identity']['username']}"
            )

            print(
                f"  Password: "
                f"{plaintext_password}"
            )

            profile = load_os_profile(
                str(os_info["profile"])
            )

            guest_family = str(
                profile.get(
                    "os",
                    {},
                ).get(
                    "family",
                    "",
                )
            ).strip().lower()

            if guest_family == "windows":
                print(
                    f"{DIM}"
                    "The Windows password exists only "
                    "in Crucible runtime state and the "
                    "generated unattended media. "
                    ".crucible/ is ignored by Git."
                    f"{RESET}"
                )

            else:
                print(
                    f"{DIM}"
                    "The plaintext password is not "
                    "written to the manifest."
                    f"{RESET}"
                )

        forge_machine(machine_path)

        verify_machine_ready(
                    machine_path
                )

        print()
        print(
            f"{GREEN}{BOLD}"
            "=========================================="
            f"{RESET}"
        )

        print(
            f"{GREEN}{BOLD}"
            "          FORGE COMPLETE"
            f"{RESET}"
        )

        print(
            f"{GREEN}{BOLD}"
            "=========================================="
            f"{RESET}"
        )

        return 0

    except (
        CrucibleForgeError,
        CrucibleError,
        UbuntuAutoinstallError,
        KaliPreseedError,
        PreseedServerError,
        FileNotFoundError,
        ValueError,
        KeyError,
        VirtualBoxError,
        WindowsUnattendError,
        SshIdentityError,
    ) as exc:
        print(
            f"\n{RED}ERROR: {exc}{RESET}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
