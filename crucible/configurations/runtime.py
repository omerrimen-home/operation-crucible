from __future__ import annotations

from typing import Any

from crucible.configurations.catalog import (
    ConfigurationDefinition,
    resolve_configuration_parameters,
)
from crucible.hardening.planner import (
    HardeningPlan,
    hardening_plan_to_runtime,
)
from crucible.networking.management import (
    MANAGEMENT_HOST_IP,
)


class ConfigurationRuntimeError(
    ValueError
):
    """
    Raised when a resolved configuration cannot be
    converted into execution-time variables.
    """


def _manifest_configuration_entries(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Index manifest configuration entries by ID.
    """

    raw_entries = manifest.get(
        "configurations",
        [],
    )

    if not isinstance(
        raw_entries,
        list,
    ):
        raise ConfigurationRuntimeError(
            "manifest.configurations "
            "must be a list."
        )

    entries: dict[
        str,
        dict[str, Any]
    ] = {}

    for entry in raw_entries:

        if not isinstance(
            entry,
            dict,
        ):
            raise ConfigurationRuntimeError(
                "Manifest configuration "
                "entry must be a mapping."
            )

        configuration_id = str(
            entry.get(
                "id",
                "",
            )
        ).strip()

        if not configuration_id:
            raise ConfigurationRuntimeError(
                "Manifest configuration "
                "entry has no id."
            )

        entries[
            configuration_id
        ] = entry

    return entries


def build_configuration_runtime_context(
    manifest: dict[str, Any],
    definitions: tuple[
        ConfigurationDefinition,
        ...
    ],
    *,
    current_configuration_id: str,
    hardening_plans: (
        dict[str, HardeningPlan]
        | None
    ) = None,
) -> dict[str, Any]:
    """
    Build variables passed to an Ansible
    configuration playbook.

    Crucially, firewall contracts from ALL selected
    configurations are included, not merely the
    configuration currently executing.
    """

    entries = (
        _manifest_configuration_entries(
            manifest
        )
    )

    resolved_configurations: list[
        dict[str, Any]
    ] = []

    firewall_inbound: list[
        dict[str, Any]
    ] = []

    firewall_forward: list[
        dict[str, Any]
    ] = []

    current_configuration: (
        dict[str, Any]
        | None
    ) = None

    for definition in definitions:

        entry = entries.get(
            definition.id,
            {},
        )

        parameters = (
            resolve_configuration_parameters(
                definition,
                entry.get(
                    "parameters",
                    {},
                ),
            )
        )

        runtime_definition = {
            "id": definition.id,
            "display_name": (
                definition.display_name
            ),
            "parameters": (
                parameters
            ),
        }

        resolved_configurations.append(
            runtime_definition
        )

        if (
            definition.id
            == current_configuration_id
        ):
            current_configuration = (
                runtime_definition
            )

        for rule in (
            definition
            .firewall
            .get(
                "inbound",
                [],
            )
        ):
            resolved_rule = dict(
                rule
            )

            resolved_rule[
                "owner_configuration"
            ] = definition.id

            firewall_inbound.append(
                resolved_rule
            )

        for rule in (
            definition
            .firewall
            .get(
                "forward",
                [],
            )
        ):
            resolved_rule = dict(
                rule
            )

            resolved_rule[
                "owner_configuration"
            ] = definition.id

            firewall_forward.append(
                resolved_rule
            )

    if current_configuration is None:
        raise ConfigurationRuntimeError(
            "Current configuration "
            f"'{current_configuration_id}' "
            "is not part of the resolved "
            "configuration set."
        )

    instance = manifest.get(
        "instance",
        {},
    )

    network = manifest.get(
        "network",
        {},
    )

    context = {
        "crucible_machine": {
            "name": (
                str(
                    manifest.get(
                        "name",
                        "",
                    )
                )
            ),

            "profile": (
                str(
                    manifest.get(
                        "profile",
                        "",
                    )
                )
            ),

            "instance_serial": (
                str(
                    instance.get(
                        "serial",
                        "",
                    )
                )
            ),

            "network": (
                network
            ),
        },

        "crucible_configurations": (
            resolved_configurations
        ),

        "crucible_current_configuration": (
            current_configuration
        ),

        "crucible_firewall": {
            "management_controller_ipv4": (
                MANAGEMENT_HOST_IP
            ),

            "inbound": (
                firewall_inbound
            ),

            "forward": (
                firewall_forward
            ),
        },
    }

    if hardening_plans is not None:

        hardening_plan = (
            hardening_plans.get(
                current_configuration_id
            )
        )

        if hardening_plan is not None:

            context[
                "crucible_hardening"
            ] = (
                hardening_plan_to_runtime(
                    hardening_plan
                )
            )

    return context