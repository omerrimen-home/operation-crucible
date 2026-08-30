from __future__ import annotations

from dataclasses import dataclass


MAX_NIC_SLOTS = 8


@dataclass(frozen=True)
class NetworkSlotLayout:
    """
    Canonical Operation Crucible NIC ordering.

    Persistent user/topology interfaces occupy the
    lowest NIC slots.

    Crucible infrastructure interfaces are appended.
    """

    topology_slots: tuple[int, ...]
    internet_slot: int | None
    management_slot: int | None


def build_network_slot_layout(
    topology_count: int,
    *,
    internet_enabled: bool = True,
    management_enabled: bool = True,
    max_slots: int = MAX_NIC_SLOTS,
) -> NetworkSlotLayout:

    if topology_count < 0:
        raise ValueError(
            "topology_count may not be negative."
        )

    infrastructure_count = (
        int(
            internet_enabled
        )
        +
        int(
            management_enabled
        )
    )

    total_count = (
        topology_count
        +
        infrastructure_count
    )

    if total_count > max_slots:
        raise ValueError(
            f"Network layout requires "
            f"{total_count} NICs, but only "
            f"{max_slots} are available."
        )

    topology_slots = tuple(
        range(
            1,
            topology_count + 1,
        )
    )

    next_slot = (
        topology_count + 1
    )

    internet_slot: int | None = None

    if internet_enabled:
        internet_slot = (
            next_slot
        )

        next_slot += 1

    management_slot: (
        int | None
    ) = None

    if management_enabled:
        management_slot = (
            next_slot
        )

    return NetworkSlotLayout(
        topology_slots=(
            topology_slots
        ),
        internet_slot=(
            internet_slot
        ),
        management_slot=(
            management_slot
        ),
    )


def legacy_linux_interface_for_slot(
    slot: int,
) -> str:

    if (
        slot < 1
        or slot > MAX_NIC_SLOTS
    ):
        raise ValueError(
            f"NIC slot must be between "
            f"1 and {MAX_NIC_SLOTS}; "
            f"got {slot}."
        )

    return f"eth{slot - 1}"