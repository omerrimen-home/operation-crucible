from __future__ import annotations

from typing import Any

from crucible.configurations.catalog import (
    ConfigurationDefinition,
    resolve_configuration_parameters,
)

from crucible.hardening.catalog import (
    HardeningCatalog,
    HardeningCatalogError,
)

from crucible.hardening.planner import (
    HardeningPlan,
    build_hardening_plan,
)


def _configuration_entries_by_id(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:

    raw_entries = manifest.get(
        "configurations",
        [],
    )

    if not isinstance(
        raw_entries,
        list,
    ):
        raise HardeningCatalogError(
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
            raise HardeningCatalogError(
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
            raise HardeningCatalogError(
                "Manifest configuration "
                "entry has no id."
            )

        entries[
            configuration_id
        ] = entry

    return entries


def validate_manifest_hardening(
    manifest: dict[str, Any],
    definitions: tuple[
        ConfigurationDefinition,
        ...
    ],
    hardening_catalog: HardeningCatalog,
) -> dict[
    str,
    HardeningPlan
]:
    """
    Resolve every selected configuration that carries
    hardening metadata.

    This function is deliberately usable during the
    create-machine preflight, before VirtualBox performs
    any work.
    """

    machine_profile_id = str(
        manifest.get(
            "profile",
            "",
        )
    ).strip()

    if not machine_profile_id:
        raise HardeningCatalogError(
            "Machine manifest has no profile."
        )

    entries = (
        _configuration_entries_by_id(
            manifest
        )
    )

    plans: dict[
        str,
        HardeningPlan
    ] = {}

    for definition in definitions:

        hardening = (
            definition.hardening
        )

        if hardening is None:
            continue

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

        profile_parameter = str(
            hardening[
                "profile_parameter"
            ]
        )

        exceptions_parameter = str(
            hardening[
                "exceptions_parameter"
            ]
        )

        requested_profile = str(
            parameters[
                profile_parameter
            ]
        ).strip()

        raw_exceptions = (
            parameters[
                exceptions_parameter
            ]
        )

        if not isinstance(
            raw_exceptions,
            list,
        ):
            raise HardeningCatalogError(
                f"Configuration "
                f"'{definition.id}' "
                f"parameter "
                f"'{exceptions_parameter}' "
                "must be a list."
            )

        plan = (
            build_hardening_plan(
                hardening_catalog,
                benchmark_id=(
                    str(
                        hardening[
                            "benchmark"
                        ]
                    )
                ),
                machine_profile_id=(
                    machine_profile_id
                ),
                requested_profile=(
                    requested_profile
                ),
                exceptions=[
                    str(
                        control_id
                    )

                    for control_id
                    in raw_exceptions
                ],
            )
        )

        plans[
            definition.id
        ] = plan

    return plans