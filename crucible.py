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
from crucible.cli.create_machine import create_machine


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

SUPPORTED_VM_COUNT = 1

SUPPORTED_OPERATING_SYSTEMS = {
    "1": {
        "name": "Ubuntu Server",
        "version": "26.04",
        "profile": "ubuntu-26.04-server",
        "image_id": "ubuntu-26.04-server",
        "default_vm_name": "ubuntu-server-01",
    }
}

DEFAULT_HARDWARE = {
    "cpus": 2,
    "memory_mb": 2048,
    "disk_gb": 20,
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


def ask_hardware_defaults() -> dict[str, int]:
    print()
    print(f"{BOLD}VM hardware defaults:{RESET}")
    print()
    print(f"  CPUs        : {DEFAULT_HARDWARE['cpus']}")
    print(f"  Memory      : {DEFAULT_HARDWARE['memory_mb']} MB")
    print(f"  Virtual disk: {DEFAULT_HARDWARE['disk_gb']} GB")
    print("  Disk type   : Dynamically allocated VDI")
    print("  Networks    : Crucible management network + NAT temporary internet access")
    print()

    while True:
        if ask_yes_no(
            f"{BOLD}Use VM hardware defaults?{RESET}",
            default=True,
        ):
            return dict(DEFAULT_HARDWARE)

        print()
        print(
            f"{RED}Custom VM hardware is not exposed in Crucible "
            f"v0.1 yet.{RESET}"
        )
        print("The default hardware configuration must currently be used.")
        print()


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


def show_autoinstall_defaults(
    vm_name: str,
    detected_key: str | None,
) -> None:
    print()
    print(f"{BOLD}Ubuntu autoinstall defaults:{RESET}")
    print()
    print(f"  Hostname        : {vm_name}")
    print(f"  User            : {DEFAULT_AUTOINSTALL['username']}")
    print(f"  Real name       : {DEFAULT_AUTOINSTALL['realname']}")
    print(f"  Locale          : {DEFAULT_AUTOINSTALL['locale']}")
    print(f"  Timezone        : {DEFAULT_AUTOINSTALL['timezone']}")
    print(f"  Keyboard        : {DEFAULT_AUTOINSTALL['keyboard_layout']}")
    print(f"  Storage layout  : {DEFAULT_AUTOINSTALL['storage_layout']}")
    print(f"  Security updates: {DEFAULT_AUTOINSTALL['updates']}")
    print("  OpenSSH server  : yes")
    print("  SSH password    : allowed")
    print("  Login password  : securely generated")

    if detected_key:
        print("  SSH public key  : detected and included")
    else:
        print("  SSH public key  : none detected")

    print()


def ask_autoinstall(
    vm_name: str,
) -> tuple[dict[str, Any], str | None]:
    detected_key = detect_ssh_public_key()
    show_autoinstall_defaults(vm_name, detected_key)

    use_defaults = ask_yes_no(
        f"{BOLD}Use Ubuntu autoinstall defaults?{RESET}",
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

    hostname = ask_with_default("Hostname", vm_name)
    username = ask_with_default(
        "Username",
        DEFAULT_AUTOINSTALL["username"],
    )
    realname = ask_with_default(
        "Real name",
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
        "Keyboard layout",
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


def build_machine_manifest(
    os_info: dict[str, Any],
    hardware: dict[str, int],
    autoinstall: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": os_info["default_vm_name"],
        "profile": os_info["profile"],
        "image_id": os_info["image_id"],
        "resources": {
            "cpus": hardware["cpus"],
            "memory_mb": hardware["memory_mb"],
            "disk_gb": hardware["disk_gb"],
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
                "address": "172.31.255.10/24",
            },
        },
        "autoinstall": autoinstall,
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
    hardware: dict[str, int],
    autoinstall: dict[str, Any],
) -> tuple[Path, Path]:
    vm_name = os_info["default_vm_name"]

    machine_path = MACHINE_MANIFEST_DIR / f"{vm_name}.yml"
    lab_path = LAB_MANIFEST_DIR / "crucible-lab.yml"

    machine_manifest = build_machine_manifest(
        os_info,
        hardware,
        autoinstall,
    )

    write_yaml(
        machine_path,
        machine_manifest,
    )

    lab_manifest = build_lab_manifest(
        machine_path,
        vm_name,
    )

    write_yaml(
        lab_path,
        lab_manifest,
    )

    return lab_path, machine_path

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

    # Convert:
    #
    # 172.31.255.10/24
    #
    # into:
    #
    # 172.31.255.10
    management_ip = management_address.split(
        "/",
        1,
    )[0]

    return (
        machine_name,
        management_ip,
        username,
    )

def wait_for_ssh(
    host: str,
    *,
    port: int = 22,
    timeout: int = 1800,
    poll_interval: float = 3.0,
) -> None:
    """
    Wait until the VM begins accepting TCP connections on SSH.
    """

    print()
    print(
        f"{CYAN}Waiting for SSH on "
        f"{host}:{port}...{RESET}"
    )

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            with socket.create_connection(
                (host, port),
                timeout=2.0,
            ):
                print(
                    f"{GREEN}[✓]{RESET} "
                    f"SSH port is reachable."
                )
                return

        except OSError:
            time.sleep(poll_interval)

    raise CrucibleForgeError(
        f"Timed out waiting for SSH on "
        f"{host}:{port}."
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

def verify_machine_ready(
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

def main() -> int:
    try:
        show_banner()

        vm_count = ask_vm_count()
        os_info = ask_operating_system()
        hardware = ask_hardware_defaults()

        if vm_count != SUPPORTED_VM_COUNT:
            raise CrucibleForgeError(
                "Unsupported VM count reached orchestration layer."
            )

        vm_name = str(os_info["default_vm_name"])

        autoinstall, plaintext_password = ask_autoinstall(vm_name)

        print()
        print(f"{CYAN}Generating Crucible manifests...{RESET}")

        lab_path, machine_path = generate_manifests(
            os_info,
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
                f"{YELLOW}{BOLD}Generated login credentials{RESET}"
            )
            print(
                f"  Username: "
                f"{autoinstall['identity']['username']}"
            )
            print(f"  Password: {plaintext_password}")
            print(
                f"{DIM}"
                "The plaintext password is not written to the manifest."
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
        FileNotFoundError,
        ValueError,
        KeyError,
    ) as exc:
        print(
            f"\n{RED}ERROR: {exc}{RESET}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
