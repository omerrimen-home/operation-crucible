from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from typing import Any

import yaml

from crucible.hardening.planner import (
    HardeningPlan,
    hardening_plan_to_runtime,
)


def _utc_timestamp() -> str:

    return (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )


def write_hardening_execution_report(
    *,
    repo_root: Path,
    machine_name: str,
    instance_serial: str,
    configuration_id: str,
    plan: HardeningPlan,
    execution_status: str,
    message: str | None = None,
) -> Path:
    """
    Write controller-side hardening state.

    IMPORTANT:

    A successful Ansible playbook does not, by itself,
    prove benchmark compliance.

    Until benchmark-specific validation is implemented,
    compliance_status therefore remains "unverified".
    """

    report_dir = (
        repo_root
        / ".crucible"
        / "state"
        / "hardening"
        / machine_name
    )

    report_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        report_dir
        / f"{configuration_id}.yml"
    )

    runtime = (
        hardening_plan_to_runtime(
            plan
        )
    )

    report: dict[str, Any] = {
        "schema_version": 1,

        "machine": (
            machine_name
        ),

        "instance_serial": (
            instance_serial
        ),

        "configuration": (
            configuration_id
        ),

        "benchmark": (
            runtime[
                "benchmark"
            ]
        ),

        "profile": (
            runtime[
                "profile"
            ]
        ),

        "plan": {
            "controls": (
                runtime[
                    "controls"
                ]
            ),

            "counts": (
                runtime[
                    "counts"
                ]
            ),
        },

        "execution": {
            "status": (
                execution_status
            ),

            "updated_at": (
                _utc_timestamp()
            ),
        },

        "compliance": {
            "status": "unverified",
        },
    }

    if message:

        report[
            "execution"
        ][
            "message"
        ] = message

    with report_path.open(
        "w",
        encoding="utf-8",
    ) as handle:

        yaml.safe_dump(
            report,
            handle,
            sort_keys=False,
        )

    report_path.chmod(
        0o600
    )

    return report_path