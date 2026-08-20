from __future__ import annotations

from typing import Any


CPU_MIN = 1
CPU_MAX = 4

MEMORY_MB_MIN = 1024
MEMORY_MB_MAX = 8192

DISK_GB_MIN = 10
DISK_GB_MAX = 75

VRAM_MB_MIN = 16
VRAM_MB_MAX = 128

MAX_NIC_SLOTS = 8
BASE_NIC_COUNT = 2
MAX_INTERNAL_NICS = MAX_NIC_SLOTS - BASE_NIC_COUNT

GRAPHICS_CONTROLLERS = {
    "vmsvga",
    "vboxsvga",
    "vboxvga",
}

FIRMWARE_TYPES = {
    "efi",
    "bios",
}


class HardwareValidationError(ValueError):
    """Raised when a machine manifest requests invalid VM hardware."""


def _validate_range(
    name: str,
    value: int,
    minimum: int,
    maximum: int,
) -> None:
    if value < minimum or value > maximum:
        raise HardwareValidationError(
            f"{name} must be between "
            f"{minimum} and {maximum}; got {value}."
        )


def validate_machine_hardware(
    manifest: dict[str, Any],
) -> None:
    """
    Validate machine-level hardware overrides.

    Missing values are allowed because the OS profile/provider
    may supply defaults.
    """

    resources = manifest.get("resources", {})
    virtualbox = manifest.get("virtualbox", {})
    graphics = virtualbox.get("graphics", {})
    network = manifest.get("network", {})

    if "cpus" in resources:
        _validate_range(
            "cpus",
            int(resources["cpus"]),
            CPU_MIN,
            CPU_MAX,
        )

    if "memory_mb" in resources:
        _validate_range(
            "memory_mb",
            int(resources["memory_mb"]),
            MEMORY_MB_MIN,
            MEMORY_MB_MAX,
        )

    if "disk_gb" in resources:
        _validate_range(
            "disk_gb",
            int(resources["disk_gb"]),
            DISK_GB_MIN,
            DISK_GB_MAX,
        )

    if "vram_mb" in graphics:
        _validate_range(
            "vram_mb",
            int(graphics["vram_mb"]),
            VRAM_MB_MIN,
            VRAM_MB_MAX,
        )

    firmware = virtualbox.get("firmware")

    if firmware is not None:
        firmware = str(firmware).lower()

        if firmware not in FIRMWARE_TYPES:
            raise HardwareValidationError(
                "firmware must be 'efi' or 'bios'."
            )

    controller = graphics.get("controller")

    if controller is not None:
        controller = str(controller).lower()

        if controller not in GRAPHICS_CONTROLLERS:
            raise HardwareValidationError(
                "graphics controller must be one of: "
                + ", ".join(sorted(GRAPHICS_CONTROLLERS))
            )

    accelerate_3d = bool(
        graphics.get("accelerate_3d", False)
    )

    if (
        controller == "vboxvga"
        and accelerate_3d
    ):
        raise HardwareValidationError(
            "3D acceleration cannot be enabled "
            "with the legacy VBoxVGA controller."
        )

    internal_networks = network.get(
        "internal",
        [],
    )

    if not isinstance(internal_networks, list):
        raise HardwareValidationError(
            "network.internal must be a list."
        )

    if len(internal_networks) > MAX_INTERNAL_NICS:
        raise HardwareValidationError(
            f"A maximum of {MAX_INTERNAL_NICS} "
            "internal networks is supported."
        )

    used_names: set[str] = set()
    used_slots = {1, 2}

    for index, nic in enumerate(
        internal_networks,
        start=3,
    ):
        if not isinstance(nic, dict):
            raise HardwareValidationError(
                "Each internal NIC must be a mapping."
            )

        name = str(
            nic.get("name", "")
        ).strip()

        if not name:
            raise HardwareValidationError(
                "Each internal NIC requires a name."
            )

        if name in used_names:
            raise HardwareValidationError(
                f"Duplicate internal network name: {name}"
            )

        slot = int(
            nic.get("slot", index)
        )

        if slot < 3 or slot > MAX_NIC_SLOTS:
            raise HardwareValidationError(
                "Internal NIC slots must be between "
                "3 and 8."
            )

        if slot in used_slots:
            raise HardwareValidationError(
                f"NIC slot {slot} is already in use."
            )

        used_names.add(name)
        used_slots.add(slot)
