#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from crucible.cli.create_machine import create_machine


# ============================================================
# Paths
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent

MACHINE_MANIFEST_DIR = REPO_ROOT / "manifests" / "machines"
LAB_MANIFEST_DIR = REPO_ROOT / "manifests" / "labs"


# ============================================================
# Current v0.1 capabilities
# ============================================================

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


# ============================================================
# Terminal appearance
# ============================================================

USE_COLOR = sys.stdout.isatty()

RESET = "\033[0m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""
DIM = "\033[2m" if USE_COLOR else ""
GOLD = "\033[38;5;214m" if USE_COLOR else ""
RED = "\033[31m" if USE_COLOR else ""
GREEN = "\033[32m" if USE_COLOR else ""
CYAN = "\033[36m" if USE_COLOR else ""


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
        "Describe the environment you need and Crucible will "
        "construct it.\n"
    )


# ============================================================
# User questions
# ============================================================

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
            f"{RED}Crucible v0.1 currently supports exactly "
            f"one VM.{RESET}"
        )
        print()


def ask_operating_system() -> dict[str, Any]:
    print()
    print(f"{BOLD}What operating system are you looking for?{RESET}")
    print()

    for key, os_info in SUPPORTED_OPERATING_SYSTEMS.items():
        print(
            f"  [{key}] "
            f"{os_info['name']} {os_info['version']}"
        )

    print()

    while True:
        answer = input("Selection [1]: ").strip()

        if not answer:
            answer = "1"

        if answer in SUPPORTED_OPERATING_SYSTEMS:
            return SUPPORTED_OPERATING_SYSTEMS[answer]

        print()
        print(
            f"{RED}That operating system is not currently "
            f"supported by Crucible.{RESET}"
        )
        print()


def ask_hardware_defaults() -> dict[str, int]:
    print()
    print(f"{BOLD}VM hardware defaults:{RESET}")
    print()
    print(f"  CPUs        : {DEFAULT_HARDWARE['cpus']}")
    print(
        f"  Memory      : "
        f"{DEFAULT_HARDWARE['memory_mb']} MB"
    )
    print(
        f"  Virtual disk: "
        f"{DEFAULT_HARDWARE['disk_gb']} GB"
    )
    print("  Disk type   : Dynamically allocated VDI")
    print("  Network     : Crucible management network")
    print()

    while True:
        answer = input(
            f"{BOLD}Use VM hardware defaults?{RESET} [Y]: "
        ).strip().lower()

        if not answer:
            answer = "y"

        if answer in {"y", "yes"}:
            return dict(DEFAULT_HARDWARE)

        print()
        print(
            f"{RED}Custom VM hardware is not exposed in "
            f"Crucible v0.1 yet.{RESET}"
        )
        print(
            "The default hardware configuration must currently "
            "be used."
        )
        print()


# ============================================================
# Manifest generation
# ============================================================

def build_machine_manifest(
    os_info: dict[str, Any],
    hardware: dict[str, int],
) -> dict[str, Any]:

    return {
        "schema_version": 1,

        "name": os_info["default_vm_name"],

        "profile": os_info["profile"],

        # Logical image ID.
        #
        # This is intentionally NOT an ISO filename.
        "image_id": os_info["image_id"],

        "resources": {
            "cpus": hardware["cpus"],
            "memory_mb": hardware["memory_mb"],
            "disk_gb": hardware["disk_gb"],
        },

        "network": {
            "management": {
                "enabled": True,
                "slot": 1,
            }
        },

        "start": {
            "enabled": True,
            "headless": False,
        },
    }


def build_lab_manifest(
    machine_manifest_path: Path,
) -> dict[str, Any]:

    relative_machine_path = (
        machine_manifest_path
        .relative_to(REPO_ROOT)
        .as_posix()
    )

    return {
        "schema_version": 1,

        "name": "crucible-lab",

        "machines": [
            {
                "name": "ubuntu-server-01",
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
) -> tuple[Path, Path]:

    vm_name = os_info["default_vm_name"]

    machine_path = (
        MACHINE_MANIFEST_DIR
        / f"{vm_name}.yml"
    )

    lab_path = (
        LAB_MANIFEST_DIR
        / "crucible-lab.yml"
    )

    machine_manifest = build_machine_manifest(
        os_info,
        hardware,
    )

    write_yaml(
        machine_path,
        machine_manifest,
    )

    lab_manifest = build_lab_manifest(
        machine_path,
    )

    write_yaml(
        lab_path,
        lab_manifest,
    )

    return lab_path, machine_path


# ============================================================
# Forge
# ============================================================

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


# ============================================================
# Main
# ============================================================

def main() -> int:
    show_banner()

    # --------------------------------------------------------
    # Gather desired topology
    # --------------------------------------------------------

    vm_count = ask_vm_count()

    os_info = ask_operating_system()

    hardware = ask_hardware_defaults()

    # vm_count is deliberately simple for v0.1.
    #
    # Later this becomes a loop that collects one definition
    # for each requested machine.
    if vm_count != SUPPORTED_VM_COUNT:
        raise RuntimeError(
            "Unsupported VM count reached orchestration layer."
        )

    # --------------------------------------------------------
    # Generate manifests
    # --------------------------------------------------------

    print()
    print(f"{CYAN}Generating Crucible manifests...{RESET}")

    lab_path, machine_path = generate_manifests(
        os_info,
        hardware,
    )

    print()
    print(f"{GREEN}[✓]{RESET} Topology manifest:")
    print(f"    {lab_path.relative_to(REPO_ROOT)}")

    print()
    print(f"{GREEN}[✓]{RESET} Machine manifest:")
    print(f"    {machine_path.relative_to(REPO_ROOT)}")

    # --------------------------------------------------------
    # Create the environment
    # --------------------------------------------------------

    forge_machine(machine_path)

    print()
    print(
        f"{GREEN}{BOLD}"
        "Forge complete."
        f"{RESET}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
