from __future__ import annotations

from typing import Any


def derive_machine_hardening_capabilities(
    profile: dict[
        str,
        Any
    ],
) -> tuple[
    str,
    ...
]:
    """
    Derive semantic hardening capabilities from
    the selected Crucible OS profile.

    These capabilities describe machine infrastructure
    that exists independently of selected post-forge
    configurations.

    Example:

        Windows 10 profile

            transport: psrp
            protocol: https

        becomes:

            management:psrp
            management:https
            management:winrm

    The management:winrm alias is deliberate because
    Crucible's PSRP implementation is transported through
    the guest's WinRM / WS-Management service.
    """

    capabilities: set[
        str
    ] = set()


    management = profile.get(
        "management",
        {},
    )


    if not isinstance(
        management,
        dict,
    ):

        return ()


    transport = str(
        management.get(
            "transport",
            "",
        )
    ).strip().lower()


    protocol = str(
        management.get(
            "protocol",
            "",
        )
    ).strip().lower()


    if transport:

        capabilities.add(
            f"management:{transport}"
        )


    if protocol:

        capabilities.add(
            f"management:{protocol}"
        )


    if transport in {
        "psrp",
        "winrm",
    }:

        capabilities.add(
            "management:winrm"
        )


    return tuple(
        sorted(
            capabilities
        )
    )