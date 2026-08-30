from __future__ import annotations
from typing import Any
import re

CPU_MIN = 1
CPU_MAX = 4

MEMORY_MB_MIN = 1024
MEMORY_MB_MAX = 8192

DISK_GB_MIN = 10
DISK_GB_MAX = 75

VRAM_MB_MIN = 16
VRAM_MB_MAX = 128

from crucible.networking.layout import (
    MAX_NIC_SLOTS,
    build_network_slot_layout,
)
from crucible.networking.topology import (
    TOPOLOGY_ATTACHMENT_TYPES,
    TopologyConfigurationError,
    validate_ipv4_configuration,
)

CRUCIBLE_OVERLAY_NIC_COUNT = 2

MAX_TOPOLOGY_NICS = (
    MAX_NIC_SLOTS
    - CRUCIBLE_OVERLAY_NIC_COUNT
)

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

    if (
        "internal" in network
        and
        "topology" not in network
    ):
        raise HardwareValidationError(
            "network.internal belongs to the "
            "pre-v0.3-AB manifest schema. "
            "Regenerate the machine manifest "
            "using network.topology."
        )

    topology_interfaces = (
        network.get(
            "topology",
            [],
        )
    )

    if not isinstance(
        topology_interfaces,
        list,
    ):
        raise HardwareValidationError(
            "network.topology must "
            "be a list."
        )

    if (
        len(topology_interfaces)
        > MAX_TOPOLOGY_NICS
    ):
        raise HardwareValidationError(
            f"A maximum of "
            f"{MAX_TOPOLOGY_NICS} "
            "persistent topology "
            "interfaces is supported."
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
        layout = (
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
        raise HardwareValidationError(
            str(exc)
        ) from exc

    used_labels: set[str] = set()
    used_macs: set[str] = set()
    used_intnets: set[str] = set()

    for interface, expected_slot in zip(
        topology_interfaces,
        layout.topology_slots,
    ):
        if not isinstance(
            interface,
            dict,
        ):
            raise HardwareValidationError(
                "Each topology interface "
                "must be a mapping."
            )

        label = str(
            interface.get(
                "label",
                "",
            )
        ).strip()

        if not label:
            raise HardwareValidationError(
                "Each topology interface "
                "requires a label."
            )

        if label in used_labels:
            raise HardwareValidationError(
                "Duplicate topology "
                f"interface label: {label}"
            )

        slot = int(
            interface.get(
                "slot",
                expected_slot,
            )
        )

        if slot != expected_slot:
            raise HardwareValidationError(
                f"Topology interface "
                f"'{label}' must occupy "
                f"NIC {expected_slot}; "
                f"got NIC {slot}."
            )

        mac_address = str(
            interface.get(
                "mac_address",
                "",
            )
        ).strip().upper()

        if not re.fullmatch(
            r"(?:[0-9A-F]{2}:){5}"
            r"[0-9A-F]{2}",
            mac_address,
        ):
            raise HardwareValidationError(
                f"Topology interface "
                f"'{label}' has invalid "
                f"MAC address: "
                f"{mac_address}"
            )

        if mac_address in used_macs:
            raise HardwareValidationError(
                f"Duplicate topology MAC: "
                f"{mac_address}"
            )

        attachment = (
            interface.get(
                "attachment",
                {},
            )
        )

        if not isinstance(
            attachment,
            dict,
        ):
            raise HardwareValidationError(
                f"Topology interface "
                f"'{label}' attachment "
                "must be a mapping."
            )

        attachment_type = str(
            attachment.get(
                "type",
                "",
            )
        ).strip().lower()

        if (
            attachment_type
            not in
            TOPOLOGY_ATTACHMENT_TYPES
        ):
            raise HardwareValidationError(
                f"Unsupported topology "
                f"attachment type: "
                f"{attachment_type}"
            )

        if attachment_type == "intnet":
            network_name = str(
                attachment.get(
                    "network",
                    "",
                )
            ).strip()

            if not network_name:
                raise HardwareValidationError(
                    f"Topology interface "
                    f"'{label}' requires an "
                    "internal network name."
                )

            if (
                network_name
                in used_intnets
            ):
                raise HardwareValidationError(
                    f"VM is already attached "
                    f"to internal network "
                    f"'{network_name}'."
                )

            used_intnets.add(
                network_name
            )

        elif (
            attachment_type
            == "bridged"
        ):
            adapter = str(
                attachment.get(
                    "adapter",
                    "",
                )
            ).strip()

            if not adapter:
                raise HardwareValidationError(
                    f"Bridged topology "
                    f"interface '{label}' "
                    "requires a host adapter."
                )

        try:
            validate_ipv4_configuration(
                interface.get(
                    "ipv4",
                    {},
                )
            )

        except (
            TopologyConfigurationError
        ) as exc:
            raise HardwareValidationError(
                f"Topology interface "
                f"'{label}': {exc}"
            ) from exc

        used_labels.add(
            label
        )

        used_macs.add(
            mac_address
        )

    if internet_enabled:
        expected_internet_slot = (
            layout.internet_slot
        )

        if expected_internet_slot is None:
            raise HardwareValidationError(
                "Could not resolve Internet "
                "NIC slot."
            )

        internet_slot = int(
            internet.get(
                "slot",
                expected_internet_slot,
            )
        )

        if (
            internet_slot
            != expected_internet_slot
        ):
            raise HardwareValidationError(
                "Crucible Internet NIC must "
                f"occupy slot "
                f"{expected_internet_slot}; "
                f"got {internet_slot}."
            )

    if management_enabled:
        expected_management_slot = (
            layout.management_slot
        )

        if expected_management_slot is None:
            raise HardwareValidationError(
                "Could not resolve management "
                "NIC slot."
            )

        management_slot = int(
            management.get(
                "slot",
                expected_management_slot,
            )
        )

        if (
            management_slot
            != expected_management_slot
        ):
            raise HardwareValidationError(
                "Crucible management NIC must "
                f"occupy slot "
                f"{expected_management_slot}; "
                f"got {management_slot}."
            )

def validate_profile_hardware(
    manifest: dict[str, Any],
    profile: dict[str, Any],
) -> None:
    """
    Validate the fully-resolved machine hardware against
    requirements imposed by its OS profile.
    """

    requirements = profile.get(
        "requirements",
        {},
    )

    if not requirements:
        return

    defaults = profile.get(
        "defaults",
        {},
    )

    profile_vbox = profile.get(
        "virtualbox",
        {},
    )

    profile_security = profile_vbox.get(
        "security",
        {},
    )

    resources = manifest.get(
        "resources",
        {},
    )

    machine_vbox = manifest.get(
        "virtualbox",
        {},
    )

    cpus = int(
        resources.get(
            "cpus",
            defaults.get("cpus", CPU_MIN),
        )
    )

    memory_mb = int(
        resources.get(
            "memory_mb",
            defaults.get(
                "memory_mb",
                MEMORY_MB_MIN,
            ),
        )
    )

    disk_gb = int(
        resources.get(
            "disk_gb",
            defaults.get(
                "disk_gb",
                DISK_GB_MIN,
            ),
        )
    )

    firmware = str(
        machine_vbox.get(
            "firmware",
            profile_vbox.get(
                "firmware",
                "bios",
            ),
        )
    ).lower()

    min_cpus = requirements.get(
        "min_cpus"
    )

    if (
        min_cpus is not None
        and cpus < int(min_cpus)
    ):
        raise HardwareValidationError(
            f"This OS requires at least "
            f"{min_cpus} CPUs; got {cpus}."
        )

    min_memory_mb = requirements.get(
        "min_memory_mb"
    )

    if (
        min_memory_mb is not None
        and memory_mb < int(min_memory_mb)
    ):
        raise HardwareValidationError(
            f"This OS requires at least "
            f"{min_memory_mb} MB RAM; "
            f"got {memory_mb} MB."
        )

    min_disk_gb = requirements.get(
        "min_disk_gb"
    )

    if (
        min_disk_gb is not None
        and disk_gb < int(min_disk_gb)
    ):
        raise HardwareValidationError(
            f"This OS requires at least "
            f"{min_disk_gb} GB disk; "
            f"got {disk_gb} GB."
        )

    required_firmware = (
        requirements.get(
            "firmware"
        )
    )

    if (
        required_firmware is not None
        and firmware
        != str(required_firmware).lower()
    ):
        raise HardwareValidationError(
            f"This OS requires "
            f"{required_firmware} firmware; "
            f"got {firmware}."
        )

    required_tpm = requirements.get(
        "tpm"
    )

    if required_tpm is not None:
        configured_tpm = str(
            profile_security.get(
                "tpm",
                "none",
            )
        )

        if configured_tpm != str(
            required_tpm
        ):
            raise HardwareValidationError(
                f"This OS requires TPM "
                f"{required_tpm}; profile "
                f"configures {configured_tpm}."
            )
