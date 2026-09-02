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


RISK_TIER_LABELS = {
    "1": "low",
    "2": "moderate",
    "3": "high",
}


def _validation_status(
    *,
    validation_mode: str,
    execution_status: str,
) -> str:

    if validation_mode != "inline":
        return "not_configured"

    if (
        execution_status
        == "playbook_succeeded"
    ):
        return "passed"

    if (
        execution_status
        == "playbook_failed"
    ):
        return "not_completed"

    return "pending"


def write_hardening_execution_report(
    *,
    repo_root: Path,
    machine_name: str,
    instance_serial: str,
    configuration_id: str,
    plan: HardeningPlan,
    execution_status: str,
    validation_mode: str = "none",
    implementation_wave: (
        str
        | None
    ) = None,
    message: str | None = None,
) -> Path:
    """
    Write controller-side hardening state.

    A successful hardening playbook may prove that
    Crucible's implementation-specific validation
    completed successfully.

    It does NOT, by itself, prove complete benchmark
    compliance.

    Compliance therefore remains "unverified" until
    explicit per-control compliance evaluation is
    implemented.
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

    validation_mode = str(
        validation_mode
    ).strip().lower()

    implementation_wave = (
        str(
            implementation_wave
        ).strip()

        if implementation_wave
        is not None

        else None
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

        "validation": {
            "mode": (
                validation_mode
            ),

            "scope": (
                "crucible-implementation"
            ),

            "status": (
                _validation_status(
                    validation_mode=(
                        validation_mode
                    ),
                    execution_status=(
                        execution_status
                    ),
                )
            ),
        },

        "compliance": {
            "status": "unverified",

            "note": (
                "Implementation validation does "
                "not constitute complete benchmark "
                "compliance."
            ),
        },
    }

    if implementation_wave:

        implementation = {
            "wave": (
                implementation_wave
            ),
        }

        risk_tier = (
            RISK_TIER_LABELS.get(
                implementation_wave
            )
        )

        if risk_tier:

            implementation[
                "risk_tier"
            ] = risk_tier

        report[
            "implementation"
        ] = implementation

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