from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]

MANAGEMENT_NETWORK = ipaddress.IPv4Network(
    "172.31.0.0/16"
)

MANAGEMENT_HOST_IP = "172.31.0.1"

MANAGEMENT_NETMASK = str(
    MANAGEMENT_NETWORK.netmask
)

MANAGEMENT_PREFIXLEN = (
    MANAGEMENT_NETWORK.prefixlen
)

FIRST_GUEST_IP = ipaddress.IPv4Address(
    int(MANAGEMENT_NETWORK.network_address)
    + 2
)

LAST_GUEST_IP = ipaddress.IPv4Address(
    int(MANAGEMENT_NETWORK.broadcast_address)
    - 1
)

GUEST_CAPACITY = (
    int(LAST_GUEST_IP)
    - int(FIRST_GUEST_IP)
    + 1
)

DEFAULT_STATE_PATH = (
    REPO_ROOT
    / ".crucible"
    / "state"
    / "management-ipam.yml"
)


class ManagementIPAMError(RuntimeError):
    """Raised when Crucible management IP allocation fails."""


def _is_guest_ip(
    address: ipaddress.IPv4Address,
) -> bool:
    return (
        int(FIRST_GUEST_IP)
        <= int(address)
        <= int(LAST_GUEST_IP)
    )


def _next_guest_ip(
    address: ipaddress.IPv4Address,
) -> ipaddress.IPv4Address:
    if address == LAST_GUEST_IP:
        return FIRST_GUEST_IP

    return ipaddress.IPv4Address(
        int(address) + 1
    )


def _new_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "network": str(
            MANAGEMENT_NETWORK
        ),
        "host_address": MANAGEMENT_HOST_IP,
        "next_address": str(
            FIRST_GUEST_IP
        ),
        "leases": {},
    }


def _validate_state(
    state: dict[str, Any],
) -> None:
    if state.get("schema_version") != 1:
        raise ManagementIPAMError(
            "Unsupported management IPAM "
            "state schema."
        )

    if state.get("network") != str(
        MANAGEMENT_NETWORK
    ):
        raise ManagementIPAMError(
            "Management IPAM state belongs "
            "to a different network."
        )

    if state.get(
        "host_address"
    ) != MANAGEMENT_HOST_IP:
        raise ManagementIPAMError(
            "Management IPAM state contains "
            "an unexpected host address."
        )

    try:
        next_address = ipaddress.IPv4Address(
            str(state["next_address"])
        )
    except (
        KeyError,
        ipaddress.AddressValueError,
    ) as exc:
        raise ManagementIPAMError(
            "Management IPAM state contains "
            "an invalid next_address."
        ) from exc

    if not _is_guest_ip(
        next_address
    ):
        raise ManagementIPAMError(
            "Management IPAM next_address "
            "is outside the guest pool."
        )

    leases = state.get(
        "leases"
    )

    if not isinstance(
        leases,
        dict,
    ):
        raise ManagementIPAMError(
            "Management IPAM leases "
            "must be a mapping."
        )

    used: set[
        ipaddress.IPv4Address
    ] = set()

    for machine_name, raw_address in (
        leases.items()
    ):
        if not str(
            machine_name
        ).strip():
            raise ManagementIPAMError(
                "Management IPAM contains "
                "an empty machine name."
            )

        try:
            address = ipaddress.IPv4Address(
                str(raw_address)
            )
        except ipaddress.AddressValueError as exc:
            raise ManagementIPAMError(
                "Management IPAM contains "
                f"an invalid lease: "
                f"{raw_address}"
            ) from exc

        if not _is_guest_ip(
            address
        ):
            raise ManagementIPAMError(
                f"Management lease {address} "
                "is outside the guest pool."
            )

        if address in used:
            raise ManagementIPAMError(
                f"Duplicate management lease: "
                f"{address}"
            )

        used.add(
            address
        )


def _load_state(
    state_path: Path,
) -> dict[str, Any]:
    if not state_path.is_file():
        return _new_state()

    with state_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        state = yaml.safe_load(
            file
        )

    if not isinstance(
        state,
        dict,
    ):
        raise ManagementIPAMError(
            "Management IPAM state "
            "is not valid YAML."
        )

    _validate_state(
        state
    )

    return state


def _write_state(
    state_path: Path,
    state: dict[str, Any],
) -> None:
    state_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = (
        state_path.with_name(
            state_path.name + ".tmp"
        )
    )

    with temporary_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            state,
            file,
            sort_keys=False,
        )

    os.replace(
        temporary_path,
        state_path,
    )


def allocate_management_address(
    machine_name: str,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
) -> str:
    name = machine_name.strip()

    if not name:
        raise ManagementIPAMError(
            "Cannot allocate a management "
            "address without a machine name."
        )

    state = _load_state(
        state_path
    )

    leases: dict[str, str] = dict(
        state["leases"]
    )

    # Existing logical machines keep
    # their existing management address.
    existing = leases.get(
        name
    )

    if existing:
        return (
            f"{existing}/"
            f"{MANAGEMENT_PREFIXLEN}"
        )

    used_addresses = {
        ipaddress.IPv4Address(
            str(address)
        )
        for address in leases.values()
    }

    candidate = ipaddress.IPv4Address(
        str(state["next_address"])
    )

    for _ in range(
        GUEST_CAPACITY
    ):
        if candidate not in used_addresses:
            leases[name] = str(
                candidate
            )

            state["leases"] = (
                leases
            )

            state["next_address"] = str(
                _next_guest_ip(
                    candidate
                )
            )

            _write_state(
                state_path,
                state,
            )

            return (
                f"{candidate}/"
                f"{MANAGEMENT_PREFIXLEN}"
            )

        candidate = _next_guest_ip(
            candidate
        )

    raise ManagementIPAMError(
        "Crucible management network "
        "has no free guest addresses."
    )


def release_management_address(
    machine_name: str,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
) -> bool:
    name = machine_name.strip()

    if not name:
        return False

    if not state_path.is_file():
        return False

    state = _load_state(
        state_path
    )

    leases: dict[str, str] = dict(
        state["leases"]
    )

    if name not in leases:
        return False

    del leases[name]

    state["leases"] = leases

    _write_state(
        state_path,
        state,
    )

    return True
