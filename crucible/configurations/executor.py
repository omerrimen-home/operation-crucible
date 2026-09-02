from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

import yaml

from crucible.configurations.catalog import (
    build_configuration_execution_plan,
    load_configuration_catalog,
    validate_manifest_configurations,
)

from crucible.configurations.runtime import (
    build_configuration_runtime_context,
)
from crucible.hardening.catalog import (
    load_hardening_catalog,
)

from crucible.hardening.integration import (
    validate_manifest_hardening,
)

from crucible.hardening.reporting import (
    write_hardening_execution_report,
)

REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

CONFIGURATION_CATALOG_PATH = (
    REPO_ROOT
    / "config"
    / "configurations.yml"
)

PROFILE_DIR = (
    REPO_ROOT
    / "profiles"
    / "os"
)

RUNTIME_VARS_DIR = (
    REPO_ROOT
    / ".crucible"
    / "ansible"
    / "vars"
)

EXECUTION_STATE_DIR = (
    REPO_ROOT
    / ".crucible"
    / "state"
    / "configurations"
)

HARDENING_CATALOG_PATH = (
    REPO_ROOT
    / "config"
    / "hardening.yml"
)

class ConfigurationExecutionError(
    RuntimeError
):
    """
    Raised when post-install configuration
    execution fails.
    """


def _load_yaml(
    path: Path,
) -> dict[str, Any]:

    if not path.is_file():
        raise FileNotFoundError(
            path
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
        raise ConfigurationExecutionError(
            f"Invalid YAML mapping: {path}"
        )

    return data


def _utc_timestamp() -> str:
    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def _write_yaml_private(
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
    ) as handle:

        yaml.safe_dump(
            data,
            handle,
            sort_keys=False,
        )

    path.chmod(
        0o600
    )


def _write_execution_state(
    *,
    machine_name: str,
    instance_serial: str,
    configuration_id: str,
    status: str,
    message: str | None = None,
) -> None:
    """
    Record post-install configuration execution state.

    This will be useful later for resume/reconfigure
    and multi-machine Forge workflows.
    """

    path = (
        EXECUTION_STATE_DIR
        / f"{machine_name}.yml"
    )

    if path.is_file():
        state = _load_yaml(
            path
        )

    else:
        state = {
            "schema_version": 1,
            "machine": machine_name,
            "instance_serial": (
                instance_serial
            ),
            "configurations": {},
        }

    if (
        state.get(
            "instance_serial"
        )
        != instance_serial
    ):
        state = {
            "schema_version": 1,
            "machine": machine_name,
            "instance_serial": (
                instance_serial
            ),
            "configurations": {},
        }

    configurations = (
        state.setdefault(
            "configurations",
            {},
        )
    )

    entry = {
        "status": status,
        "updated_at": (
            _utc_timestamp()
        ),
    }

    if message:
        entry[
            "message"
        ] = message

    configurations[
        configuration_id
    ] = entry

    _write_yaml_private(
        path,
        state,
    )


def execute_machine_configurations(
    machine_manifest_path: Path,
    inventory_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    """
    Execute selected Crucible configurations in
    deterministic catalog order.

    Returns IDs successfully applied.
    """

    if (
        shutil.which(
            "ansible-playbook"
        )
        is None
    ):
        raise ConfigurationExecutionError(
            "ansible-playbook was not found "
            "on the controller."
        )

    manifest = _load_yaml(
        machine_manifest_path
    )

    machine_name = str(
        manifest.get(
            "name",
            "",
        )
    ).strip()

    if not machine_name:
        raise ConfigurationExecutionError(
            "Machine manifest has no name."
        )

    profile_name = str(
        manifest.get(
            "profile",
            "",
        )
    ).strip()

    if not profile_name:
        raise ConfigurationExecutionError(
            "Machine manifest has no profile."
        )

    profile_path = (
        repo_root
        / "profiles"
        / "os"
        / f"{profile_name}.yml"
    )

    profile = _load_yaml(
        profile_path
    )

    catalog = (
        load_configuration_catalog(
            repo_root
            / "config"
            / "configurations.yml"
        )
    )

    definitions = (
        validate_manifest_configurations(
            manifest,
            profile,
            catalog,
        )
    )

    hardening_catalog = (
        load_hardening_catalog(
            repo_root
            / "config"
            / "hardening.yml",
            repo_root=(
                repo_root
            ),
        )
    )

    hardening_plans = (
        validate_manifest_hardening(
            manifest,
            definitions,
            hardening_catalog,
        )
    )

    if not definitions:

        print()
        print(
            "No post-install "
            "configurations selected."
        )

        return []

    plan = (
        build_configuration_execution_plan(
            definitions
        )
    )

    instance_serial = str(
        manifest.get(
            "instance",
            {},
        ).get(
            "serial",
            "",
        )
    )

    applied: list[str] = []

    print()
    print(
        "=========================================="
    )
    print(
        "       APPLYING CONFIGURATIONS"
    )
    print(
        "=========================================="
    )
    print()

    print(
        "Execution order:"
    )

    for index, definition in enumerate(
        plan,
        start=1,
    ):
        print(
            f"  [{index}] "
            f"{definition.display_name}"
        )

    print()

    for definition in plan:

        implementation = (
            definition.implementation
        )

        if implementation is None:
            raise ConfigurationExecutionError(
                f"Configuration "
                f"'{definition.id}' "
                "has no implementation."
            )

        backend = str(
            implementation.get(
                "backend",
                "",
            )
        ).strip().lower()

        if backend != "ansible":
            raise ConfigurationExecutionError(
                f"Unsupported configuration "
                f"backend '{backend}'."
            )

        relative_playbook = Path(
            str(
                implementation[
                    "playbook"
                ]
            )
        )

        playbook_path = (
            repo_root
            / relative_playbook
        ).resolve()

        repo_root_resolved = (
            repo_root.resolve()
        )

        try:
            playbook_path.relative_to(
                repo_root_resolved
            )

        except ValueError as exc:
            raise ConfigurationExecutionError(
                f"Configuration "
                f"'{definition.id}' "
                "playbook escapes repository root."
            ) from exc

        if not playbook_path.is_file():
            raise ConfigurationExecutionError(
                f"Configuration "
                f"'{definition.id}' "
                "playbook not found: "
                f"{playbook_path}"
            )

        runtime_context = (
            build_configuration_runtime_context(
                manifest,
                definitions,
                current_configuration_id=(
                    definition.id
                ),
                hardening_plans=(
                    hardening_plans
                ),
            )
        )

        hardening_plan = (
            hardening_plans.get(
                definition.id
            )
        )

        hardening_validation_mode = (
            "none"
        )

        hardening_implementation_wave: (
            str
            | None
        ) = None


        if (
            hardening_plan
            is not None
            and
            definition.hardening
            is not None
        ):

            hardening_validation_mode = str(
                definition
                .hardening
                .get(
                    "validation_mode",
                    "none",
                )
            ).strip().lower()


            risk_parameter = (
                definition
                .hardening
                .get(
                    "risk_parameter"
                )
            )


            if risk_parameter:

                current_parameters = (
                    runtime_context[
                        "crucible_current_configuration"
                    ][
                        "parameters"
                    ]
                )

                raw_wave = (
                    current_parameters.get(
                        str(
                            risk_parameter
                        )
                    )
                )

                if raw_wave is not None:

                    resolved_wave = str(
                        raw_wave
                    ).strip()

                    if resolved_wave:

                        hardening_implementation_wave = (
                            resolved_wave
                        )

        if hardening_plan is not None:

            write_hardening_execution_report(
                repo_root=(
                    repo_root
                ),
                machine_name=(
                    machine_name
                ),
                instance_serial=(
                    instance_serial
                ),
                configuration_id=(
                    definition.id
                ),
                plan=(
                    hardening_plan
                ),
                execution_status=(
                    "running"
                ),
                validation_mode=(
                    hardening_validation_mode
                ),

                implementation_wave=(
                    hardening_implementation_wave
                ),
            )

        vars_path = (
            repo_root
            / ".crucible"
            / "ansible"
            / "vars"
            / (
                f"{machine_name}-"
                f"{definition.id}.yml"
            )
        )

        _write_yaml_private(
            vars_path,
            runtime_context,
        )

        print()
        print(
            f"Applying: "
            f"{definition.display_name}"
        )

        print(
            f"  Playbook: "
            f"{relative_playbook}"
        )

        _write_execution_state(
            machine_name=(
                machine_name
            ),
            instance_serial=(
                instance_serial
            ),
            configuration_id=(
                definition.id
            ),
            status="running",
        )

        environment = dict(
            os.environ
        )

        environment[
            "ANSIBLE_ROLES_PATH"
        ] = str(
            repo_root
            / "ansible"
            / "roles"
        )

        result = subprocess.run(
            [
                "ansible-playbook",

                "-i",
                str(
                    inventory_path
                ),

                "--limit",
                machine_name,

                str(
                    playbook_path
                ),

                "--extra-vars",
                f"@{vars_path}",
            ],
            cwd=str(
                repo_root
            ),
            env=environment,
            text=True,
            check=False,
        )

        if result.returncode != 0:

            _write_execution_state(
                machine_name=(
                    machine_name
                ),
                instance_serial=(
                    instance_serial
                ),
                configuration_id=(
                    definition.id
                ),
                status="failed",
                message=(
                    "ansible-playbook "
                    f"returned "
                    f"{result.returncode}"
                ),
            )

            if hardening_plan is not None:

                write_hardening_execution_report(
                    repo_root=(
                        repo_root
                    ),
                    machine_name=(
                        machine_name
                    ),
                    instance_serial=(
                        instance_serial
                    ),
                    configuration_id=(
                        definition.id
                    ),
                    plan=(
                        hardening_plan
                    ),
                    execution_status=(
                        "playbook_failed"
                    ),
                    message=(
                        "ansible-playbook "
                        f"returned "
                        f"{result.returncode}"
                    ),
                    validation_mode=(
                        hardening_validation_mode
                    ),

                    implementation_wave=(
                        hardening_implementation_wave
                    ),
                )

            raise ConfigurationExecutionError(
                f"Configuration "
                f"'{definition.id}' failed."
            )

        _write_execution_state(
            machine_name=(
                machine_name
            ),
            instance_serial=(
                instance_serial
            ),
            configuration_id=(
                definition.id
            ),
            status="applied",
        )

        if hardening_plan is not None:

            write_hardening_execution_report(
                repo_root=(
                    repo_root
                ),
                machine_name=(
                    machine_name
                ),
                instance_serial=(
                    instance_serial
                ),
                configuration_id=(
                    definition.id
                ),
                plan=(
                    hardening_plan
                ),
                execution_status=(
                    "playbook_succeeded"
                ),
                validation_mode=(
                    hardening_validation_mode
                ),

                implementation_wave=(
                    hardening_implementation_wave
                ),
            )

        applied.append(
            definition.id
        )

        print(
            f"[✓] "
            f"{definition.display_name} "
            "applied."
        )

    return applied