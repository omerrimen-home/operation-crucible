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
    MAX_INTERNAL_NICS,
)
from crucible.networking.management import (
    allocate_management_address,
    management_mac_for_machine,
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
        "vm_name_prefix": "winserver2022",
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
            f"{RED}Crucible v0.1 currently supports exactly one VM.{RESET}"
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

VM_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$"
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
        "internal_networks": [],
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
        "  NIC 1              : "
        "NAT provisioning/internet"
    )
    print(
        "  NIC 2              : "
        "Crucible management"
    )
    print(
        "  Additional NICs    : none"
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

    internal_count = ask_int_with_default(
        "Additional internal networks",
        0,
        minimum=0,
        maximum=MAX_INTERNAL_NICS,
    )

    internal_networks: list[str] = []

    for number in range(
        1,
        internal_count + 1,
    ):
        while True:
            network_name = input(
                f"Internal network {number} name: "
            ).strip()

            if not network_name:
                print(
                    f"{RED}"
                    "Network name cannot be empty."
                    f"{RESET}"
                )
                continue

            if network_name in internal_networks:
                print(
                    f"{RED}"
                    "Network names must be unique."
                    f"{RESET}"
                )
                continue

            internal_networks.append(
                network_name
            )
            break

    hardware["internal_networks"] = (
        internal_networks
    )

    return hardware


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
    detected_key: str | None,
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

    if detected_key:
        print("  SSH Public Key  : detected and included")
    else:
        print("  SSH Public Key  : none detected")

    print()


def ask_autoinstall(
    vm_name: str,
) -> tuple[dict[str, Any], str | None]:
    detected_key = detect_ssh_public_key()
    show_autoinstall_defaults(vm_name, detected_key)

    use_defaults = ask_yes_no(
        f"{BOLD}Use Autoinstall Defaults?{RESET}",
        default=True,
    )

    if use_defaults:
        plaintext_password = generate_password()
        password_hash = hash_password(plaintext_password)

        authorized_keys = [detected_key] if detected_key else []

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

    install_ssh = ask_yes_no(
        "Install OpenSSH server?",
        default=True,
    )

    allow_password = False
    authorized_keys: list[str] = []

    if install_ssh:
        allow_password = ask_yes_no(
            "Allow SSH password authentication?",
            default=True,
        )

        if detected_key and ask_yes_no(
            "Include detected SSH public key?",
            default=True,
        ):
            authorized_keys.append(detected_key)

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

    OS edition, disk layout, administrator membership and
    the single bootstrap autologon remain controlled by the
    selected OS profile / Crucible provisioning design.
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

    edition = str(
        installer.get(
            "image_name",
            profile.get(
                "display_name",
                "Windows",
            ),
        )
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

        return (
            {
                "enabled": True,

                "hostname": vm_name,

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

    hostname = ask_with_default(
        "Computer Name",
        vm_name,
    )

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

    print()
    print(
        f"{DIM}"
        f"Windows edition remains fixed by profile: "
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
) -> tuple[dict[str, Any], str | None]:
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
        return ask_autoinstall(
            vm_name
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

    return {
        "schema_version": 1,
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
            "internet": {
                "enabled": True,
                "slot": 1,
                "mode": "nat",
            },

            "management": {
                "enabled": True,
                "slot": 2,
                "address": management_address,
                "mac_address": (
                    management_mac_for_machine(
                        machine_name
                    )
                ),
            },

            "internal": [
                {
                    "name": network_name,
                    "slot": slot,
                }
                for slot, network_name in enumerate(
                    hardware["internal_networks"],
                    start=3,
                )
            ],
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
) -> dict[str, Any]:
    relative_machine_path = (
        machine_manifest_path.relative_to(REPO_ROOT).as_posix()
    )

    return {
        "schema_version": 1,
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
        )
    )

    write_yaml(
        machine_path,
        machine_manifest,
    )

    lab_manifest = build_lab_manifest(
        machine_path,
        machine_name,
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
    timeout: int = 1800,
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

                    # Crucible v0.1 machines are ephemeral
                    # lab machines and may reuse the same IP
                    # with a newly generated SSH host key.
                    "ansible_ssh_common_args": (
                        "-o StrictHostKeyChecking=no "
                        "-o UserKnownHostsFile=/dev/null"
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
    machine_name: str,
    inventory_path: Path,
    timeout: int = 1800,
    poll_interval: float = 5.0,
) -> None:
    """
    Wait until bootstrap.sh has completed inside the VM.
    """

    print()
    print(
        f"{CYAN}Waiting for Crucible bootstrap "
        f"to complete...{RESET}"
    )

    deadline = time.monotonic() + timeout

    command = [
        "ansible",
        machine_name,
        "-i",
        str(inventory_path),
        "-m",
        "ansible.builtin.raw",
        "-a",
        (
            "test -f "
            "/var/lib/crucible/"
            "bootstrap-complete"
        ),
    ]

    while time.monotonic() < deadline:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode == 0:
            print(
                f"{GREEN}[✓]{RESET} "
                f"Bootstrap complete."
            )
            return

        time.sleep(poll_interval)

    raise CrucibleForgeError(
        "Timed out waiting for Linux bootstrap "
        "to complete."
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

    print()
    print(
        f"{BOLD}Management target:{RESET} "
        f"{username}@{management_ip}"
    )

    inventory_path = generate_ansible_inventory(
        machine_name=machine_name,
        host=management_ip,
        username=username,
    )

    print(
        f"{GREEN}[✓]{RESET} "
        f"Ansible inventory generated:"
    )
    print(
        f"    "
        f"{inventory_path.relative_to(REPO_ROOT)}"
    )

    wait_for_ssh(
        management_ip
    )

    wait_for_bootstrap(
        machine_name=machine_name,
        inventory_path=inventory_path,
    )

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

        os_info = ask_operating_system()

        vm_name = ask_vm_name(
            os_info
        )

        hardware = ask_hardware_defaults(
            os_info
        )

        if vm_count != SUPPORTED_VM_COUNT:
            raise CrucibleForgeError(
                "Unsupported VM count reached "
                "orchestration layer."
            )

        autoinstall, plaintext_password = (
            ask_installation_configuration(
                os_info,
                vm_name
            )
        )

        print()
        print(f"{CYAN}Generating Crucible manifests...{RESET}")

        lab_path, machine_path = generate_manifests(
            os_info,
            vm_name,
            hardware,
            autoinstall,
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
    ) as exc:
        print(
            f"\n{RED}ERROR: {exc}{RESET}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
