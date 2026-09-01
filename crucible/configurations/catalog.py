from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import re

import yaml


CONFIGURATION_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9_-]{0,63}$"
)

CAPABILITY_PATTERN = re.compile(
    r"^[a-z][a-z0-9._-]*"
    r":[a-z][a-z0-9._-]*"
    r"(?::[a-z][a-z0-9._-]*)*$"
)

SUPPORTED_OS_SELECTOR_FIELDS = {
    "profile",
    "family",
    "distribution",
    "version",
    "flavor",
    "architecture",
}

PARAMETER_NAME_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]{0,63}$"
)

HARDENING_BENCHMARK_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9._-]{0,127}$"
)

class ConfigurationCatalogError(
    ValueError
):
    """
    Raised when the Crucible configuration catalog,
    a configuration selection, or configuration
    requirements are invalid.
    """


@dataclass(
    frozen=True
)
class NetworkRequirements:
    """
    Minimum persistent-topology capabilities required
    by one or more post-install configurations.

    These are capability counts rather than exact
    interface assignments.

    For example:

        min_static_internal_interfaces = 1

    means that at least one persistent topology NIC
    must simultaneously:

        - use a VirtualBox Internal Network; and
        - have static IPv4 configuration.

    One NIC may satisfy multiple requirements.
    """

    min_topology_interfaces: int = 0

    min_static_ipv4_interfaces: int = 0

    min_internal_network_interfaces: int = 0

    min_static_internal_interfaces: int = 0


    @property
    def effective_min_topology_interfaces(
        self,
    ) -> int:
        """
        Determine the minimum number of topology NICs
        implied by all network requirements.

        A requirement for one static interface already
        implies the existence of at least one topology
        interface, for example.
        """

        return max(
            self.min_topology_interfaces,
            self.min_static_ipv4_interfaces,
            self.min_internal_network_interfaces,
            self.min_static_internal_interfaces,
        )


    @property
    def is_empty(
        self,
    ) -> bool:
        return (
            self.min_topology_interfaces
            == 0

            and

            self.min_static_ipv4_interfaces
            == 0

            and

            self.min_internal_network_interfaces
            == 0

            and

            self.min_static_internal_interfaces
            == 0
        )


@dataclass(frozen=True)
class ConfigurationDefinition:
    """
    One declarative Crucible post-install configuration.

    The catalog describes:

    - what operating systems support the configuration;
    - what topology it requires;
    - how it will eventually be executed;
    - configuration-specific parameter defaults;
    - relationships with other configurations;
    - network/firewall services it exposes.
    """

    id: str

    display_name: str

    description: str

    selectable: bool

    supported_os: tuple[
        dict[str, str],
        ...
    ]

    network_requirements: (
        NetworkRequirements
    )

    implementation: (
        dict[str, Any]
        | None
    )

    parameters: dict[
        str,
        Any
    ]

    relationships: dict[
        str,
        tuple[str, ...]
    ]

    firewall: dict[
        str,
        Any
    ]

    capabilities: tuple[
        str,
        ...
    ] = ()

    hardening: (
        dict[str, Any]
        | None
    ) = None


@dataclass(
    frozen=True
)
class ConfigurationCatalog:
    """
    Parsed and validated configuration catalog.
    """

    schema_version: int

    definitions: dict[
        str,
        ConfigurationDefinition
    ]


    def get(
        self,
        configuration_id: str,
    ) -> ConfigurationDefinition:

        try:
            return self.definitions[
                configuration_id
            ]

        except KeyError as exc:
            raise ConfigurationCatalogError(
                "Unknown Crucible configuration: "
                f"{configuration_id}"
            ) from exc


def _load_yaml_mapping(
    path: Path,
) -> dict[str, Any]:
    """
    Load a YAML file whose root must be a mapping.
    """

    if not path.is_file():
        raise FileNotFoundError(
            "Configuration catalog not found: "
            f"{path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:

        data = yaml.safe_load(
            handle
        )

    if not isinstance(
        data,
        dict,
    ):
        raise ConfigurationCatalogError(
            "Configuration catalog root "
            "must be a mapping."
        )

    return data


def _nonnegative_int(
    value: Any,
    *,
    field_name: str,
) -> int:
    """
    Resolve and validate a non-negative integer field.
    """

    if isinstance(
        value,
        bool,
    ):
        raise ConfigurationCatalogError(
            f"{field_name} must be a "
            "non-negative integer."
        )

    try:
        resolved = int(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise ConfigurationCatalogError(
            f"{field_name} must be a "
            "non-negative integer."
        ) from exc

    if resolved < 0:
        raise ConfigurationCatalogError(
            f"{field_name} may not be negative."
        )

    return resolved


def _parse_supported_os(
    configuration_id: str,
    value: Any,
) -> tuple[
    dict[str, str],
    ...
]:
    """
    Parse the supported_os list.

    A configuration may contain multiple selectors.

    Matching is OR between selectors and AND inside
    one selector.

    Example:

        supported_os:
          - family: linux
            distribution: ubuntu

          - family: linux
            distribution: kali

    means Ubuntu OR Kali.
    """

    if (
        not isinstance(
            value,
            list,
        )
        or
        not value
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            "requires a non-empty "
            "supported_os list."
        )

    selectors: list[
        dict[str, str]
    ] = []

    for index, selector in enumerate(
        value,
        start=1,
    ):

        if (
            not isinstance(
                selector,
                dict,
            )
            or
            not selector
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                f"supported_os entry "
                f"{index} must be a "
                "non-empty mapping."
            )

        unknown_fields = (
            set(
                selector
            )
            -
            SUPPORTED_OS_SELECTOR_FIELDS
        )

        if unknown_fields:
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "uses unsupported OS "
                "selector field(s): "
                +
                ", ".join(
                    sorted(
                        unknown_fields
                    )
                )
            )

        normalized: dict[
            str,
            str
        ] = {}

        for (
            key,
            raw_value,
        ) in selector.items():

            text = str(
                raw_value
            ).strip()

            if not text:
                raise ConfigurationCatalogError(
                    f"Configuration "
                    f"'{configuration_id}' "
                    f"supported_os field "
                    f"'{key}' may not "
                    "be empty."
                )

            normalized[
                key
            ] = text

        selectors.append(
            normalized
        )

    return tuple(
        selectors
    )


def _parse_network_requirements(
    configuration_id: str,
    requirements: Any,
) -> NetworkRequirements:
    """
    Parse configuration network requirements.
    """

    if requirements is None:
        return NetworkRequirements()

    if not isinstance(
        requirements,
        dict,
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            "requirements must "
            "be a mapping."
        )

    network = requirements.get(
        "network",
        {},
    )

    if not isinstance(
        network,
        dict,
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            "requirements.network "
            "must be a mapping."
        )

    allowed_fields = {
        "min_topology_interfaces",
        "min_static_ipv4_interfaces",
        "min_internal_network_interfaces",
        "min_static_internal_interfaces",
    }

    unknown_fields = (
        set(
            network
        )
        -
        allowed_fields
    )

    if unknown_fields:
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            "uses unsupported network "
            "requirement field(s): "
            +
            ", ".join(
                sorted(
                    unknown_fields
                )
            )
        )

    return NetworkRequirements(

        min_topology_interfaces=(
            _nonnegative_int(
                network.get(
                    "min_topology_interfaces",
                    0,
                ),
                field_name=(
                    f"{configuration_id}."
                    "min_topology_interfaces"
                ),
            )
        ),

        min_static_ipv4_interfaces=(
            _nonnegative_int(
                network.get(
                    "min_static_ipv4_interfaces",
                    0,
                ),
                field_name=(
                    f"{configuration_id}."
                    "min_static_ipv4_interfaces"
                ),
            )
        ),

        min_internal_network_interfaces=(
            _nonnegative_int(
                network.get(
                    "min_internal_network_interfaces",
                    0,
                ),
                field_name=(
                    f"{configuration_id}."
                    "min_internal_network_interfaces"
                ),
            )
        ),

        min_static_internal_interfaces=(
            _nonnegative_int(
                network.get(
                    "min_static_internal_interfaces",
                    0,
                ),
                field_name=(
                    f"{configuration_id}."
                    "min_static_internal_interfaces"
                ),
            )
        ),
    )

def _parse_configuration_id_list(
    configuration_id: str,
    value: Any,
    *,
    field_name: str,
) -> tuple[str, ...]:
    """
    Parse a list of configuration IDs used by
    requires/conflicts.
    """

    if value is None:
        return ()

    if not isinstance(
        value,
        list,
    ):
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            f"{field_name} must be a list."
        )

    resolved: list[str] = []

    seen: set[str] = set()

    for raw_value in value:

        target = str(
            raw_value
        ).strip()

        if not target:
            raise ConfigurationCatalogError(
                f"Configuration '{configuration_id}' "
                f"{field_name} contains an empty ID."
            )

        if not (
            CONFIGURATION_ID_PATTERN
            .fullmatch(
                target
            )
        ):
            raise ConfigurationCatalogError(
                f"Configuration '{configuration_id}' "
                f"{field_name} contains invalid "
                f"configuration ID '{target}'."
            )

        if target == configuration_id:
            raise ConfigurationCatalogError(
                f"Configuration '{configuration_id}' "
                f"may not reference itself in "
                f"{field_name}."
            )

        if target in seen:
            raise ConfigurationCatalogError(
                f"Configuration '{configuration_id}' "
                f"contains duplicate {field_name} "
                f"entry '{target}'."
            )

        seen.add(
            target
        )

        resolved.append(
            target
        )

    return tuple(
        resolved
    )

def _parse_relationships(
    configuration_id: str,
    value: Any,
) -> dict[str, tuple[str, ...]]:
    """
    Parse configuration dependencies and conflicts.
    """

    if value is None:
        value = {}

    if not isinstance(
        value,
        dict,
    ):
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "relationships must be a mapping."
        )

    unknown = (
        set(value)
        -
        {
            "requires",
            "conflicts",
        }
    )

    if unknown:
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "contains unsupported relationship "
            "field(s): "
            +
            ", ".join(
                sorted(
                    unknown
                )
            )
        )

    return {
        "requires": (
            _parse_configuration_id_list(
                configuration_id,
                value.get(
                    "requires",
                    [],
                ),
                field_name="requires",
            )
        ),

        "conflicts": (
            _parse_configuration_id_list(
                configuration_id,
                value.get(
                    "conflicts",
                    [],
                ),
                field_name="conflicts",
            )
        ),
    }

def _parse_implementation(
    configuration_id: str,
    value: Any,
    *,
    selectable: bool,
) -> dict[str, Any] | None:
    """
    Parse configuration execution metadata.

    AD currently supports one backend:

        ansible
    """

    if value is None:

        if selectable:
            raise ConfigurationCatalogError(
                f"Selectable configuration "
                f"'{configuration_id}' "
                "requires an implementation."
            )

        return None

    if not isinstance(
        value,
        dict,
    ):
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "implementation must be a mapping."
        )

    unknown = (
        set(value)
        -
        {
            "backend",
            "playbook",
            "order",
        }
    )

    if unknown:
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "contains unsupported implementation "
            "field(s): "
            +
            ", ".join(
                sorted(
                    unknown
                )
            )
        )

    backend = str(
        value.get(
            "backend",
            "",
        )
    ).strip().lower()

    if backend != "ansible":
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "currently requires implementation "
            "backend 'ansible'; "
            f"got '{backend or 'undefined'}'."
        )

    playbook = str(
        value.get(
            "playbook",
            "",
        )
    ).strip()

    if not playbook:
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "requires implementation.playbook."
        )

    raw_order = value.get(
        "order",
        500,
    )

    if isinstance(
        raw_order,
        bool,
    ):
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "implementation.order must be "
            "an integer."
        )

    try:
        order = int(
            raw_order
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "implementation.order must be "
            "an integer."
        ) from exc

    if (
        order < 0
        or
        order > 10000
    ):
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "implementation.order must be "
            "between 0 and 10000."
        )

    return {
        "backend": backend,
        "playbook": playbook,
        "order": order,
    }

def _parse_port_list(
    configuration_id: str,
    rule_id: str,
    value: Any,
    *,
    field_name: str,
) -> list[int]:
    """
    Validate TCP/UDP port lists.
    """

    if value is None:
        return []

    if not isinstance(
        value,
        list,
    ):
        raise ConfigurationCatalogError(
            f"Firewall rule '{rule_id}' in "
            f"configuration '{configuration_id}' "
            f"{field_name} must be a list."
        )

    ports: list[int] = []

    seen: set[int] = set()

    for raw_port in value:

        if isinstance(
            raw_port,
            bool,
        ):
            raise ConfigurationCatalogError(
                f"Firewall rule '{rule_id}' "
                f"contains an invalid port."
            )

        try:
            port = int(
                raw_port
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise ConfigurationCatalogError(
                f"Firewall rule '{rule_id}' "
                f"contains invalid port "
                f"'{raw_port}'."
            ) from exc

        if (
            port < 1
            or
            port > 65535
        ):
            raise ConfigurationCatalogError(
                f"Firewall rule '{rule_id}' "
                f"port {port} is outside "
                "1-65535."
            )

        if port not in seen:
            ports.append(
                port
            )

            seen.add(
                port
            )

    return ports


def _parse_firewall_rule(
    configuration_id: str,
    value: Any,
    *,
    direction: str,
) -> dict[str, Any]:
    """
    Parse one portable Crucible firewall contract.

    source_scope and destination_scope refer to
    logical Crucible interfaces, not Linux names.

    Current scopes:

        management
        topology
        internet
        any
    """

    if not isinstance(
        value,
        dict,
    ):
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            f"firewall {direction} rule "
            "must be a mapping."
        )

    rule_id = str(
        value.get(
            "id",
            "",
        )
    ).strip()

    if not rule_id:
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            f"firewall {direction} rule "
            "requires an id."
        )

    protocol = str(
        value.get(
            "protocol",
            "",
        )
    ).strip().lower()

    if protocol not in {
        "tcp",
        "udp",
    }:
        raise ConfigurationCatalogError(
            f"Firewall rule '{rule_id}' "
            "protocol must be tcp or udp."
        )

    source_scope = str(
        value.get(
            "source_scope",
            "topology",
        )
    ).strip().lower()

    valid_scopes = {
        "management",
        "topology",
        "internet",
        "any",
    }

    if source_scope not in valid_scopes:
        raise ConfigurationCatalogError(
            f"Firewall rule '{rule_id}' "
            f"has invalid source_scope "
            f"'{source_scope}'."
        )

    destination_scope: str | None = None

    if direction == "forward":

        destination_scope = str(
            value.get(
                "destination_scope",
                "topology",
            )
        ).strip().lower()

        if destination_scope not in valid_scopes:
            raise ConfigurationCatalogError(
                f"Firewall rule '{rule_id}' "
                "has invalid destination_scope "
                f"'{destination_scope}'."
            )

    ports = (
        _parse_port_list(
            configuration_id,
            rule_id,
            value.get(
                "ports",
                [],
            ),
            field_name="ports",
        )
    )

    if not ports:
        raise ConfigurationCatalogError(
            f"Firewall rule '{rule_id}' "
            "requires at least one "
            "destination port."
        )

    source_ports = (
        _parse_port_list(
            configuration_id,
            rule_id,
            value.get(
                "source_ports",
                [],
            ),
            field_name="source_ports",
        )
    )

    source_addresses = (
        value.get(
            "source_addresses",
            [],
        )
    )

    if not isinstance(
        source_addresses,
        list,
    ):
        raise ConfigurationCatalogError(
            f"Firewall rule '{rule_id}' "
            "source_addresses must be a list."
        )

    normalized_addresses = [
        str(address).strip()

        for address
        in source_addresses

        if str(address).strip()
    ]

    comment = str(
        value.get(
            "comment",
            rule_id,
        )
    ).strip()

    return {
        "id": rule_id,
        "direction": direction,
        "protocol": protocol,
        "ports": ports,
        "source_ports": source_ports,
        "source_scope": source_scope,
        "destination_scope": (
            destination_scope
        ),
        "source_addresses": (
            normalized_addresses
        ),
        "comment": comment,
    }


def _parse_firewall_contract(
    configuration_id: str,
    value: Any,
) -> dict[str, Any]:
    """
    Parse portable firewall requirements published
    by a Crucible configuration.
    """

    if value is None:
        value = {}

    if not isinstance(
        value,
        dict,
    ):
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "firewall must be a mapping."
        )

    unknown = (
        set(value)
        -
        {
            "inbound",
            "forward",
        }
    )

    if unknown:
        raise ConfigurationCatalogError(
            f"Configuration '{configuration_id}' "
            "contains unsupported firewall "
            "field(s): "
            +
            ", ".join(
                sorted(
                    unknown
                )
            )
        )

    result = {
        "inbound": [],
        "forward": [],
    }

    for direction in (
        "inbound",
        "forward",
    ):

        raw_rules = value.get(
            direction,
            [],
        )

        if not isinstance(
            raw_rules,
            list,
        ):
            raise ConfigurationCatalogError(
                f"Configuration '{configuration_id}' "
                f"firewall.{direction} "
                "must be a list."
            )

        used_ids: set[str] = set()

        for raw_rule in raw_rules:

            rule = (
                _parse_firewall_rule(
                    configuration_id,
                    raw_rule,
                    direction=(
                        direction
                    ),
                )
            )

            if rule["id"] in used_ids:
                raise ConfigurationCatalogError(
                    f"Configuration "
                    f"'{configuration_id}' "
                    "contains duplicate firewall "
                    f"rule '{rule['id']}'."
                )

            used_ids.add(
                rule["id"]
            )

            result[
                direction
            ].append(
                rule
            )

    return result

def _parse_hardening_reference(
    configuration_id: str,
    value: Any,
    *,
    parameters: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Parse the optional benchmark relationship carried
    by a hardening configuration.

    The actual benchmark definition lives in
    config/hardening.yml.
    """

    if value is None:
        return None

    if not isinstance(
        value,
        dict,
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            "hardening must be a mapping."
        )

    unknown = (
        set(
            value
        )
        -
        {
            "benchmark",
            "profile_parameter",
            "exceptions_parameter",
            "risk_parameter",
            "max_implemented_wave",
        }
    )

    if unknown:
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            "contains unsupported "
            "hardening field(s): "
            +
            ", ".join(
                sorted(
                    unknown
                )
            )
        )

    benchmark = str(
        value.get(
            "benchmark",
            "",
        )
    ).strip()

    if not (
        HARDENING_BENCHMARK_ID_PATTERN
        .fullmatch(
            benchmark
        )
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            "contains invalid "
            f"hardening benchmark "
            f"'{benchmark}'."
        )

    profile_parameter = str(
        value.get(
            "profile_parameter",
            "profile",
        )
    ).strip()

    exceptions_parameter = str(
        value.get(
            "exceptions_parameter",
            "exceptions",
        )
    ).strip()

    raw_risk_parameter = (
        value.get(
            "risk_parameter"
        )
    )

    risk_parameter: (
        str
        | None
    ) = None

    max_implemented_wave: (
        int
        | None
    ) = None


    if raw_risk_parameter is not None:

        risk_parameter = str(
            raw_risk_parameter
        ).strip()

        if not (
            PARAMETER_NAME_PATTERN
            .fullmatch(
                risk_parameter
            )
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "hardening.risk_parameter "
                "contains invalid parameter "
                f"name '{risk_parameter}'."
            )

        if (
            risk_parameter
            not in parameters
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "hardening.risk_parameter "
                "references undefined "
                f"configuration parameter "
                f"'{risk_parameter}'."
            )

        risk_default = (
            parameters[
                risk_parameter
            ]
        )

        if (
            not isinstance(
                risk_default,
                str,
            )
            or
            risk_default
            not in {
                "1",
                "2",
                "3",
            }
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                f"parameter '{risk_parameter}' "
                "must have a string default "
                "of '1', '2', or '3'."
            )


        raw_max_wave = (
            value.get(
                "max_implemented_wave",
                1,
            )
        )

        if isinstance(
            raw_max_wave,
            bool,
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "max_implemented_wave "
                "must be an integer."
            )

        try:

            max_implemented_wave = int(
                raw_max_wave
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "max_implemented_wave "
                "must be an integer."
            ) from exc


        if (
            max_implemented_wave
            not in {
                1,
                2,
                3,
            }
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "max_implemented_wave "
                "must be 1, 2, or 3."
            )

    for (
        field_name,
        parameter_name,
    ) in (
        (
            "profile_parameter",
            profile_parameter,
        ),
        (
            "exceptions_parameter",
            exceptions_parameter,
        ),
    ):

        if not (
            PARAMETER_NAME_PATTERN
            .fullmatch(
                parameter_name
            )
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                f"hardening.{field_name} "
                "contains invalid parameter "
                f"name '{parameter_name}'."
            )

        if (
            parameter_name
            not in parameters
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                f"hardening.{field_name} "
                "references undefined "
                f"configuration parameter "
                f"'{parameter_name}'."
            )

    if not isinstance(
        parameters[
            profile_parameter
        ],
        str,
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            f"hardening profile parameter "
            f"'{profile_parameter}' "
            "must have a string default."
        )

    if not isinstance(
        parameters[
            exceptions_parameter
        ],
        list,
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            f"hardening exceptions parameter "
            f"'{exceptions_parameter}' "
            "must have a list default."
        )

    hardening = {
        "benchmark": benchmark,

        "profile_parameter": (
            profile_parameter
        ),

        "exceptions_parameter": (
            exceptions_parameter
        ),
    }


    if risk_parameter is not None:

        hardening[
            "risk_parameter"
        ] = risk_parameter

        hardening[
            "max_implemented_wave"
        ] = (
            max_implemented_wave
        )


    return hardening


def _parse_capabilities(
    configuration_id: str,
    value: Any,
) -> tuple[str, ...]:
    """
    Parse semantic capabilities provided by a
    configuration.

    Capabilities describe what the final machine is
    intentionally expected to do.

    Examples:

        service:dns-server
        service:dhcp-server
        service:web-server
        protocol:sctp
        network:ipv4-router
    """

    if value is None:
        return ()

    if not isinstance(
        value,
        list,
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{configuration_id}' "
            "capabilities must be a list."
        )

    capabilities: list[
        str
    ] = []

    seen: set[
        str
    ] = set()

    for raw_capability in value:

        capability = str(
            raw_capability
        ).strip().lower()

        if not (
            CAPABILITY_PATTERN
            .fullmatch(
                capability
            )
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "contains invalid capability "
                f"{capability!r}."
            )

        if capability in seen:
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "contains duplicate capability "
                f"'{capability}'."
            )

        seen.add(
            capability
        )

        capabilities.append(
            capability
        )

    return tuple(
        capabilities
    )

def load_configuration_catalog(
    path: Path,
) -> ConfigurationCatalog:
    """
    Load and validate config/configurations.yml.
    """

    data = _load_yaml_mapping(
        path
    )

    schema_version = (
        _nonnegative_int(
            data.get(
                "schema_version",
                0,
            ),
            field_name=(
                "schema_version"
            ),
        )
    )

    if schema_version != 1:
        raise ConfigurationCatalogError(
            "Unsupported configuration "
            "catalog schema_version: "
            f"{schema_version}"
        )

    raw_definitions = data.get(
        "configurations"
    )

    if (
        not isinstance(
            raw_definitions,
            dict,
        )
        or
        not raw_definitions
    ):
        raise ConfigurationCatalogError(
            "Configuration catalog "
            "requires a non-empty "
            "configurations mapping."
        )

    definitions: dict[
        str,
        ConfigurationDefinition
    ] = {}

    for (
        raw_id,
        raw_definition,
    ) in raw_definitions.items():

        configuration_id = str(
            raw_id
        ).strip()

        if not (
            CONFIGURATION_ID_PATTERN
            .fullmatch(
                configuration_id
            )
        ):
            raise ConfigurationCatalogError(
                "Invalid configuration id: "
                f"{configuration_id!r}"
            )

        if not isinstance(
            raw_definition,
            dict,
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "must be a mapping."
            )

        display_name = str(
            raw_definition.get(
                "display_name",
                "",
            )
        ).strip()

        if not display_name:
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "requires display_name."
            )

        description = str(
            raw_definition.get(
                "description",
                "",
            )
        ).strip()

        if not description:
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "requires description."
            )

        selectable = (
            raw_definition.get(
                "selectable",
                True,
            )
        )

        if not isinstance(
            selectable,
            bool,
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "selectable must be "
                "true or false."
            )

        supported_os = (
            _parse_supported_os(
                configuration_id,
                raw_definition.get(
                    "supported_os"
                ),
            )
        )

        network_requirements = (
            _parse_network_requirements(
                configuration_id,
                raw_definition.get(
                    "requirements",
                    {},
                ),
            )
        )

        implementation = (
            _parse_implementation(
                configuration_id,
                raw_definition.get(
                    "implementation"
                ),
                selectable=(
                    selectable
                ),
            )
        )

        if (
            implementation
            is not None
            and
            not isinstance(
                implementation,
                dict,
            )
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "implementation must "
                "be a mapping or null."
            )

        relationships = (
            _parse_relationships(
                configuration_id,
                raw_definition.get(
                    "relationships",
                    {},
                ),
            )
        )

        capabilities = (
            _parse_capabilities(
                configuration_id,
                raw_definition.get(
                    "capabilities",
                    [],
                ),
            )
        )

        firewall = (
            _parse_firewall_contract(
                configuration_id,
                raw_definition.get(
                    "firewall",
                    {},
                ),
            )
        )

        parameters = (
            raw_definition.get(
                "parameters",
                {},
            )
        )

        if not isinstance(
            parameters,
            dict,
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "parameters must "
                "be a mapping."
            )

        hardening = (
            _parse_hardening_reference(
                configuration_id,
                raw_definition.get(
                    "hardening"
                ),
                parameters=(
                    parameters
                ),
            )
        )

        definitions[
            configuration_id
        ] = (
            ConfigurationDefinition(

                id=(
                    configuration_id
                ),

                display_name=(
                    display_name
                ),

                description=(
                    description
                ),

                selectable=(
                    selectable
                ),

                supported_os=(
                    supported_os
                ),

                network_requirements=(
                    network_requirements
                ),

                implementation=(
                    implementation
                ),

                parameters=(
                    dict(
                        parameters
                    )
                ),
                relationships=(
                    relationships
                ),

                firewall=(
                    firewall
                ),
                capabilities=(
                    capabilities
                ),
                hardening=(
                    hardening
                ),
            )
        )

    catalog = ConfigurationCatalog(
        schema_version=(
            schema_version
        ),
        definitions=(
            definitions
        ),
    )

    _validate_catalog_relationships(
        catalog
    )

    return catalog

def _validate_catalog_relationships(
    catalog: ConfigurationCatalog,
) -> None:
    """
    Validate cross-configuration references after every
    definition has been parsed.
    """

    known_ids = set(
        catalog.definitions
    )

    for definition in (
        catalog.definitions.values()
    ):

        for required_id in (
            definition
            .relationships[
                "requires"
            ]
        ):

            if required_id not in known_ids:
                raise ConfigurationCatalogError(
                    f"Configuration "
                    f"'{definition.id}' "
                    "requires unknown "
                    "configuration "
                    f"'{required_id}'."
                )

        for conflicting_id in (
            definition
            .relationships[
                "conflicts"
            ]
        ):

            if conflicting_id not in known_ids:
                raise ConfigurationCatalogError(
                    f"Configuration "
                    f"'{definition.id}' "
                    "conflicts with unknown "
                    "configuration "
                    f"'{conflicting_id}'."
                )

def profile_matches_selector(
    profile: dict[str, Any],
    selector: dict[str, str],
) -> bool:
    """
    Return True if an OS profile satisfies one
    supported_os selector.

    Example profile data:

        id: ubuntu-26.04-server

        os:
          family: linux
          distribution: ubuntu
          version: "26.04"
          flavor: server
          architecture: amd64
    """

    profile_os = profile.get(
        "os",
        {},
    )

    if not isinstance(
        profile_os,
        dict,
    ):
        return False

    for (
        key,
        expected,
    ) in selector.items():

        if key == "profile":
            actual = profile.get(
                "id"
            )

        else:
            actual = profile_os.get(
                key
            )

        if actual is None:
            return False

        if (
            str(
                actual
            ).strip().lower()
            !=
            str(
                expected
            ).strip().lower()
        ):
            return False

    return True

def combine_configuration_capabilities(
    definitions: Iterable[
        ConfigurationDefinition
    ],
) -> tuple[str, ...]:
    """
    Return the semantic capability union provided by
    all selected configurations.

    Ordering is deterministic for stable runtime vars
    and tests.
    """

    capabilities = {
        capability

        for definition
        in definitions

        for capability
        in definition.capabilities
    }

    return tuple(
        sorted(
            capabilities
        )
    )

def configuration_supports_profile(
    definition: (
        ConfigurationDefinition
    ),
    profile: dict[str, Any],
) -> bool:
    """
    A configuration is compatible if any one
    supported_os selector matches.
    """

    return any(

        profile_matches_selector(
            profile,
            selector,
        )

        for selector
        in definition.supported_os
    )


def compatible_configurations(
    catalog: ConfigurationCatalog,
    profile: dict[str, Any],
    *,
    selectable_only: bool = True,
) -> list[
    ConfigurationDefinition
]:
    """
    Return catalog entries compatible with an
    OS profile.
    """

    compatible = [

        definition

        for definition
        in catalog.definitions.values()

        if (
            configuration_supports_profile(
                definition,
                profile,
            )

            and

            (
                not selectable_only
                or
                definition.selectable
            )
        )
    ]

    return sorted(
        compatible,
        key=lambda definition: (
            definition
            .display_name
            .lower()
        ),
    )


def resolve_configuration_ids(
    configuration_ids: Iterable[
        str
    ],
    catalog: ConfigurationCatalog,
    profile: dict[str, Any],
    *,
    require_selectable: bool = True,
) -> tuple[
    ConfigurationDefinition,
    ...
]:
    """
    Resolve a collection of selected configuration IDs.

    Also verifies:

        - the ID exists;
        - it is not duplicated;
        - it is selectable when required;
        - it supports the selected OS.
    """

    resolved: list[
        ConfigurationDefinition
    ] = []

    seen: set[
        str
    ] = set()

    for raw_id in configuration_ids:

        configuration_id = str(
            raw_id
        ).strip()

        if not configuration_id:
            raise ConfigurationCatalogError(
                "Selected configuration id "
                "may not be empty."
            )

        if configuration_id in seen:
            raise ConfigurationCatalogError(
                "Duplicate selected "
                "configuration: "
                f"{configuration_id}"
            )

        definition = catalog.get(
            configuration_id
        )

        if (
            require_selectable
            and
            not definition.selectable
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "exists in the catalog "
                "but is not selectable yet."
            )

        if not (
            configuration_supports_profile(
                definition,
                profile,
            )
        ):
            profile_name = str(
                profile.get(
                    "id",
                    "unknown",
                )
            )

            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "is not compatible with "
                "OS profile "
                f"'{profile_name}'."
            )

        resolved.append(
            definition
        )

        seen.add(
            configuration_id
        )

    selected_ids = {
        definition.id

        for definition
        in resolved
    }

    for definition in resolved:

        for required_id in (
            definition
            .relationships[
                "requires"
            ]
        ):

            if required_id not in selected_ids:
                raise ConfigurationCatalogError(
                    f"Configuration "
                    f"'{definition.id}' "
                    "requires configuration "
                    f"'{required_id}'."
                )

        for conflicting_id in (
            definition
            .relationships[
                "conflicts"
            ]
        ):

            if conflicting_id in selected_ids:
                raise ConfigurationCatalogError(
                    f"Configuration "
                    f"'{definition.id}' "
                    "conflicts with "
                    f"'{conflicting_id}'."
                )

    return tuple(
        resolved
    )

def resolve_configuration_parameters(
    definition: ConfigurationDefinition,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge machine-manifest parameter overrides with
    catalog defaults.

    Unknown parameters are rejected so typos do not
    silently become ignored configuration.
    """

    if not isinstance(
        overrides,
        dict,
    ):
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{definition.id}' "
            "parameters must be a mapping."
        )

    defaults = dict(
        definition.parameters
    )

    unknown = (
        set(overrides)
        -
        set(defaults)
    )

    if unknown:
        raise ConfigurationCatalogError(
            f"Configuration "
            f"'{definition.id}' "
            "contains unknown parameter(s): "
            +
            ", ".join(
                sorted(
                    unknown
                )
            )
        )

    resolved = dict(
        defaults
    )

    for (
        key,
        value,
    ) in overrides.items():

        default = defaults[
            key
        ]

        if default is not None:

            expected_type = type(
                default
            )

            if (
                expected_type is int
                and
                isinstance(
                    value,
                    bool,
                )
            ):
                raise ConfigurationCatalogError(
                    f"Configuration "
                    f"'{definition.id}' "
                    f"parameter '{key}' "
                    "must be an integer."
                )

            if not isinstance(
                value,
                expected_type,
            ):
                raise ConfigurationCatalogError(
                    f"Configuration "
                    f"'{definition.id}' "
                    f"parameter '{key}' "
                    "must be of type "
                    f"{expected_type.__name__}."
                )

        resolved[
            key
        ] = value

    return resolved

def combine_network_requirements(
    definitions: Iterable[
        ConfigurationDefinition
    ],
) -> NetworkRequirements:
    """
    Combine multiple selected configurations into
    one effective network requirement.

    A NIC can satisfy requirements for more than one
    configuration, so each minimum is combined using
    max(), rather than adding the requirements.
    """

    definitions = tuple(
        definitions
    )

    if not definitions:
        return NetworkRequirements()

    return NetworkRequirements(

        min_topology_interfaces=max(
            definition
            .network_requirements
            .min_topology_interfaces

            for definition
            in definitions
        ),

        min_static_ipv4_interfaces=max(
            definition
            .network_requirements
            .min_static_ipv4_interfaces

            for definition
            in definitions
        ),

        min_internal_network_interfaces=max(
            definition
            .network_requirements
            .min_internal_network_interfaces

            for definition
            in definitions
        ),

        min_static_internal_interfaces=max(
            definition
            .network_requirements
            .min_static_internal_interfaces

            for definition
            in definitions
        ),
    )


def validate_topology_requirements(
    topology_interfaces: Any,
    requirements: NetworkRequirements,
) -> None:
    """
    Verify that an already-defined Crucible topology
    satisfies configuration requirements.

    This intentionally uses the canonical topology
    representation created by milestone AB.
    """

    if not isinstance(
        topology_interfaces,
        list,
    ):
        raise ConfigurationCatalogError(
            "Topology interfaces must "
            "be a list before "
            "configuration requirements "
            "can be validated."
        )

    total_count = len(
        topology_interfaces
    )

    static_count = 0

    internal_count = 0

    static_internal_count = 0

    for interface in topology_interfaces:

        if not isinstance(
            interface,
            dict,
        ):
            continue

        attachment = interface.get(
            "attachment",
            {},
        )

        ipv4 = interface.get(
            "ipv4",
            {},
        )

        if isinstance(
            attachment,
            dict,
        ):
            attachment_type = str(
                attachment.get(
                    "type",
                    "",
                )
            ).strip().lower()

        else:
            attachment_type = ""

        if isinstance(
            ipv4,
            dict,
        ):
            ipv4_method = str(
                ipv4.get(
                    "method",
                    "",
                )
            ).strip().lower()

        else:
            ipv4_method = ""

        is_internal = (
            attachment_type
            == "intnet"
        )

        is_static = (
            ipv4_method
            == "static"
        )

        if is_internal:
            internal_count += 1

        if is_static:
            static_count += 1

        if (
            is_internal
            and
            is_static
        ):
            static_internal_count += 1

    minimum_total = (
        requirements
        .effective_min_topology_interfaces
    )

    if total_count < minimum_total:
        raise ConfigurationCatalogError(
            "Selected configuration(s) "
            "require at least "
            f"{minimum_total} persistent "
            "topology interface(s); "
            f"got {total_count}."
        )

    if (
        static_count
        <
        requirements
        .min_static_ipv4_interfaces
    ):
        raise ConfigurationCatalogError(
            "Selected configuration(s) "
            "require at least "
            f"{requirements.min_static_ipv4_interfaces} "
            "topology interface(s) "
            "using static IPv4; "
            f"got {static_count}."
        )

    if (
        internal_count
        <
        requirements
        .min_internal_network_interfaces
    ):
        raise ConfigurationCatalogError(
            "Selected configuration(s) "
            "require at least "
            f"{requirements.min_internal_network_interfaces} "
            "VirtualBox Internal "
            "Network interface(s); "
            f"got {internal_count}."
        )

    if (
        static_internal_count
        <
        requirements
        .min_static_internal_interfaces
    ):
        raise ConfigurationCatalogError(
            "Selected configuration(s) "
            "require at least "
            f"{requirements.min_static_internal_interfaces} "
            "Internal Network "
            "interface(s) using "
            "static IPv4; "
            f"got {static_internal_count}."
        )

def build_configuration_execution_plan(
    definitions: tuple[
        ConfigurationDefinition,
        ...
    ],
) -> tuple[
    ConfigurationDefinition,
    ...
]:
    """
    Return selected configurations in deterministic
    execution order.
    """

    for definition in definitions:

        if definition.implementation is None:
            raise ConfigurationCatalogError(
                f"Selected configuration "
                f"'{definition.id}' "
                "has no implementation."
            )

    return tuple(
        sorted(
            definitions,
            key=lambda definition: (
                int(
                    definition
                    .implementation
                    .get(
                        "order",
                        500,
                    )
                ),
                definition.id,
            ),
        )
    )

def validate_manifest_configurations(
    manifest: dict[str, Any],
    profile: dict[str, Any],
    catalog: ConfigurationCatalog,
) -> tuple[
    ConfigurationDefinition,
    ...
]:
    """
    Validate the configuration section of a fully
    resolved machine manifest.

    Canonical manifest representation:

        configurations:
          - id: nftables
            parameters: {}

    AC validates this representation.

    AD will later consume it and execute the declared
    Ansible implementation.
    """

    raw_selection = manifest.get(
        "configurations",
        [],
    )

    if not isinstance(
        raw_selection,
        list,
    ):
        raise ConfigurationCatalogError(
            "manifest.configurations "
            "must be a list."
        )

    configuration_ids: list[
        str
    ] = []

    for (
        index,
        entry,
    ) in enumerate(
        raw_selection,
        start=1,
    ):

        if not isinstance(
            entry,
            dict,
        ):
            raise ConfigurationCatalogError(
                "Each manifest "
                "configuration must "
                "be a mapping; "
                f"entry {index} "
                "is invalid."
            )

        configuration_id = str(
            entry.get(
                "id",
                "",
            )
        ).strip()

        if not configuration_id:
            raise ConfigurationCatalogError(
                "Manifest configuration "
                f"entry {index} "
                "requires an id."
            )

        parameters = entry.get(
            "parameters",
            {},
        )

        if not isinstance(
            parameters,
            dict,
        ):
            raise ConfigurationCatalogError(
                f"Configuration "
                f"'{configuration_id}' "
                "parameters must "
                "be a mapping."
            )

        configuration_ids.append(
            configuration_id
        )

    definitions = (
        resolve_configuration_ids(
            configuration_ids,
            catalog,
            profile,
            require_selectable=True,
        )
    )

    for (
        entry,
        definition,
    ) in zip(
        raw_selection,
        definitions,
    ):

        resolve_configuration_parameters(
            definition,
            entry.get(
                "parameters",
                {},
            ),
        )

    network = manifest.get(
        "network",
        {},
    )

    if isinstance(
        network,
        dict,
    ):
        topology_interfaces = (
            network.get(
                "topology",
                [],
            )
        )

    else:
        topology_interfaces = []

    requirements = (
        combine_network_requirements(
            definitions
        )
    )

    validate_topology_requirements(
        topology_interfaces,
        requirements,
    )

    return definitions