from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any


TOPOLOGY_ATTACHMENT_TYPES = {
    "intnet": "Internal Network",
    "bridged": "Bridged Adapter",
}


TOPOLOGY_LABEL_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$"
)


# Keep Crucible's temporary NAT route preferred while
# the Forge infrastructure still exists.
CRUCIBLE_NAT_ROUTE_METRIC = 50

# Persistent topology default routes remain usable but
# rank below Crucible's temporary NAT route.
TOPOLOGY_ROUTE_METRIC = 200


class TopologyConfigurationError(ValueError):
    """Raised when topology NIC configuration is invalid."""


def topology_mac_for_machine(
    machine_name: str,
    slot: int,
) -> str:
    """
    Generate a deterministic locally-administered MAC
    address for a persistent topology interface.

    The identity is tied to machine name + persistent
    topology slot.

    Examples:

        ubuntu-01 / NIC 1
        ubuntu-01 / NIC 2

    will always receive the same MACs when rebuilt.
    """

    name = machine_name.strip()

    if not name:
        raise TopologyConfigurationError(
            "Cannot generate topology MAC "
            "without a machine name."
        )

    if slot < 1 or slot > 8:
        raise TopologyConfigurationError(
            "Topology NIC slot must be "
            f"between 1 and 8; got {slot}."
        )

    digest = hashlib.sha256(
        (
            "operation-crucible:topology:"
            f"{name}:{slot}"
        ).encode("utf-8")
    ).digest()

    octets = [
        0x02,
        digest[0],
        digest[1],
        digest[2],
        digest[3],
        digest[4],
    ]

    return ":".join(
        f"{octet:02X}"
        for octet in octets
    )


def subnet_mask_to_prefix(
    subnet_mask: str,
) -> int:
    """
    Convert a subnet mask to a CIDR prefix length.

    Accepts:

        255.255.255.0
        255.255.0.0
        24
        16
    """

    value = subnet_mask.strip()

    if not value:
        raise TopologyConfigurationError(
            "Subnet mask may not be empty."
        )

    if value.isdigit():
        prefix = int(value)

        if prefix < 0 or prefix > 32:
            raise TopologyConfigurationError(
                "IPv4 prefix length must be "
                "between 0 and 32."
            )

        return prefix

    try:
        network = ipaddress.IPv4Network(
            f"0.0.0.0/{value}"
        )

    except ValueError as exc:
        raise TopologyConfigurationError(
            f"Invalid subnet mask: {value}"
        ) from exc

    return network.prefixlen


def build_dhcp_ipv4_configuration(
) -> dict[str, Any]:
    """
    Canonical DHCP IPv4 configuration.

    Keep address/gateway keys present even when unused.
    This makes Linux, Windows and future manifest parsing
    simpler and predictable.
    """

    return {
        "method": "dhcp",
        "address": None,
        "gateway": None,
    }


def build_static_ipv4_configuration(
    *,
    address: str,
    subnet_mask: str,
    gateway: str | None,
) -> dict[str, Any]:
    """
    Validate user-entered static IPv4 information and
    normalize it into Crucible's canonical CIDR form.
    """

    try:
        ip_address = ipaddress.IPv4Address(
            address.strip()
        )

    except ipaddress.AddressValueError as exc:
        raise TopologyConfigurationError(
            f"Invalid IPv4 address: {address}"
        ) from exc

    if (
        ip_address.is_unspecified
        or ip_address.is_multicast
    ):
        raise TopologyConfigurationError(
            f"IPv4 address is not usable: "
            f"{ip_address}"
        )

    prefix_length = (
        subnet_mask_to_prefix(
            subnet_mask
        )
    )

    interface = ipaddress.IPv4Interface(
        f"{ip_address}/{prefix_length}"
    )

    gateway_value: str | None = None

    if gateway is not None:
        gateway = gateway.strip()

        if gateway:
            try:
                gateway_address = (
                    ipaddress.IPv4Address(
                        gateway
                    )
                )

            except (
                ipaddress.AddressValueError
            ) as exc:
                raise TopologyConfigurationError(
                    f"Invalid default gateway: "
                    f"{gateway}"
                ) from exc

            if (
                gateway_address
                not in interface.network
            ):
                raise TopologyConfigurationError(
                    f"Gateway {gateway_address} "
                    "is not within subnet "
                    f"{interface.network}."
                )

            if (
                gateway_address
                == ip_address
            ):
                raise TopologyConfigurationError(
                    "The interface address and "
                    "default gateway may not "
                    "be identical."
                )

            gateway_value = str(
                gateway_address
            )

    return {
        "method": "static",
        "address": str(
            interface
        ),
        "gateway": gateway_value,
    }


def validate_ipv4_configuration(
    ipv4: dict[str, Any],
) -> None:
    """
    Validate canonical topology IPv4 configuration.
    """

    if not isinstance(
        ipv4,
        dict,
    ):
        raise TopologyConfigurationError(
            "Topology IPv4 configuration "
            "must be a mapping."
        )

    method = str(
        ipv4.get(
            "method",
            "",
        )
    ).strip().lower()

    if method == "dhcp":
        return

    if method != "static":
        raise TopologyConfigurationError(
            "Topology IPv4 method must be "
            "'dhcp' or 'static'."
        )

    raw_address = str(
        ipv4.get(
            "address",
            "",
        )
    ).strip()

    if not raw_address:
        raise TopologyConfigurationError(
            "Static IPv4 configuration "
            "requires an address."
        )

    try:
        interface = (
            ipaddress.IPv4Interface(
                raw_address
            )
        )

    except ValueError as exc:
        raise TopologyConfigurationError(
            "Invalid static IPv4 address: "
            f"{raw_address}"
        ) from exc

    gateway = ipv4.get(
        "gateway"
    )

    if gateway in {
        None,
        "",
    }:
        return

    try:
        gateway_address = (
            ipaddress.IPv4Address(
                str(gateway)
            )
        )

    except (
        ipaddress.AddressValueError
    ) as exc:
        raise TopologyConfigurationError(
            "Invalid topology gateway: "
            f"{gateway}"
        ) from exc

    if (
        gateway_address
        not in interface.network
    ):
        raise TopologyConfigurationError(
            f"Gateway {gateway_address} "
            "is outside interface network "
            f"{interface.network}."
        )