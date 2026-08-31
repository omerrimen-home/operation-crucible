from __future__ import annotations

from dataclasses import dataclass

from crucible.hardening.catalog import (
    HardeningBenchmarkDefinition,
    HardeningCatalog,
    HardeningCatalogError,
    HardeningControlDefinition,
    HardeningProfileDefinition,
    load_benchmark_controls,
)


class HardeningPlanningError(
    ValueError
):
    """
    Raised when Crucible cannot construct a safe,
    unambiguous hardening plan.
    """


@dataclass(
    frozen=True
)
class HardeningPlan:
    """
    Fully resolved hardening plan for one machine
    configuration.
    """

    benchmark: (
        HardeningBenchmarkDefinition
    )

    profile: (
        HardeningProfileDefinition
    )

    applicable_controls: tuple[
        HardeningControlDefinition,
        ...
    ]

    automated_control_ids: tuple[
        str,
        ...
    ]

    manual_control_ids: tuple[
        str,
        ...
    ]

    not_implemented_control_ids: tuple[
        str,
        ...
    ]

    exception_control_ids: tuple[
        str,
        ...
    ]


def resolve_hardening_profile(
    benchmark: HardeningBenchmarkDefinition,
    *,
    machine_profile_id: str,
    requested_profile: str = "auto",
) -> HardeningProfileDefinition:
    """
    Resolve either an explicitly requested benchmark
    profile or the benchmark's automatic default.
    """

    machine_profile_id = str(
        machine_profile_id
    ).strip()

    requested_profile = str(
        requested_profile
    ).strip().lower()

    if (
        machine_profile_id
        not in benchmark.supported_profiles
    ):
        raise HardeningPlanningError(
            f"Benchmark '{benchmark.id}' "
            "does not support Crucible OS profile "
            f"'{machine_profile_id}'."
        )

    if not benchmark.profiles:
        raise HardeningPlanningError(
            f"Benchmark '{benchmark.id}' "
            "does not define any executable "
            "benchmark profiles."
        )

    if (
        requested_profile
        and
        requested_profile != "auto"
    ):

        try:
            profile = (
                benchmark.profiles[
                    requested_profile
                ]
            )

        except KeyError as exc:
            raise HardeningPlanningError(
                f"Benchmark '{benchmark.id}' "
                "does not contain profile "
                f"'{requested_profile}'."
            ) from exc

        if (
            profile.applies_to_profiles
            and
            machine_profile_id
            not in profile.applies_to_profiles
        ):
            raise HardeningPlanningError(
                f"Benchmark profile "
                f"'{profile.id}' "
                "does not apply to Crucible "
                f"OS profile "
                f"'{machine_profile_id}'."
            )

        return profile

    default_candidates = [
        profile

        for profile
        in benchmark.profiles.values()

        if (
            machine_profile_id
            in profile.default_for_profiles
        )
    ]

    if len(
        default_candidates
    ) == 1:
        return (
            default_candidates[
                0
            ]
        )

    if len(
        default_candidates
    ) > 1:
        raise HardeningPlanningError(
            f"Benchmark '{benchmark.id}' "
            "contains multiple automatic "
            "profiles for Crucible OS profile "
            f"'{machine_profile_id}'."
        )

    applicable_profiles = [
        profile

        for profile
        in benchmark.profiles.values()

        if (
            not profile.applies_to_profiles
            or
            machine_profile_id
            in profile.applies_to_profiles
        )
    ]

    if len(
        applicable_profiles
    ) == 1:
        return (
            applicable_profiles[
                0
            ]
        )

    raise HardeningPlanningError(
        f"Benchmark '{benchmark.id}' "
        "cannot automatically determine "
        "a benchmark profile for "
        f"'{machine_profile_id}'. "
        "Select a profile explicitly."
    )


def build_hardening_plan(
    catalog: HardeningCatalog,
    *,
    benchmark_id: str,
    machine_profile_id: str,
    requested_profile: str = "auto",
    exceptions: list[str] | tuple[str, ...] = (),
) -> HardeningPlan:
    """
    Produce the exact benchmark/control plan Crucible
    will expose to the Ansible implementation.
    """

    benchmark = catalog.get(
        benchmark_id
    )

    if benchmark.status != "implemented":
        raise HardeningPlanningError(
            f"Benchmark '{benchmark.id}' "
            f"is currently '{benchmark.status}' "
            "and cannot be executed."
        )

    profile = (
        resolve_hardening_profile(
            benchmark,
            machine_profile_id=(
                machine_profile_id
            ),
            requested_profile=(
                requested_profile
            ),
        )
    )

    controls = (
        load_benchmark_controls(
            benchmark
        )
    )

    applicable_controls = tuple(
        control

        for control
        in controls

        if (
            profile.id
            in control.profiles
        )
    )

    if not applicable_controls:
        raise HardeningPlanningError(
            f"Benchmark '{benchmark.id}' "
            f"profile '{profile.id}' "
            "contains no applicable controls."
        )

    normalized_exceptions: list[
        str
    ] = []

    seen: set[
        str
    ] = set()

    for raw_control_id in exceptions:

        control_id = str(
            raw_control_id
        ).strip()

        if not control_id:
            raise HardeningPlanningError(
                "Hardening exception control "
                "ID may not be empty."
            )

        if control_id in seen:
            raise HardeningPlanningError(
                "Duplicate hardening exception: "
                f"{control_id}"
            )

        seen.add(
            control_id
        )

        normalized_exceptions.append(
            control_id
        )

    applicable_ids = {
        control.id

        for control
        in applicable_controls
    }

    invalid_exceptions = (
        set(
            normalized_exceptions
        )
        -
        applicable_ids
    )

    if invalid_exceptions:
        raise HardeningPlanningError(
            f"Benchmark '{benchmark.id}' "
            f"profile '{profile.id}' "
            "does not contain exception "
            "control(s): "
            +
            ", ".join(
                sorted(
                    invalid_exceptions
                )
            )
        )

    exception_ids = set(
        normalized_exceptions
    )

    automated_control_ids: list[
        str
    ] = []

    manual_control_ids: list[
        str
    ] = []

    not_implemented_control_ids: list[
        str
    ] = []

    for control in applicable_controls:

        if control.id in exception_ids:
            continue

        if (
            control.crucible_implementation
            == "automated"
        ):
            automated_control_ids.append(
                control.id
            )

        elif (
            control.crucible_implementation
            == "manual"
        ):
            manual_control_ids.append(
                control.id
            )

        else:
            not_implemented_control_ids.append(
                control.id
            )

    return HardeningPlan(
        benchmark=benchmark,
        profile=profile,
        applicable_controls=(
            applicable_controls
        ),
        automated_control_ids=tuple(
            automated_control_ids
        ),
        manual_control_ids=tuple(
            manual_control_ids
        ),
        not_implemented_control_ids=tuple(
            not_implemented_control_ids
        ),
        exception_control_ids=tuple(
            normalized_exceptions
        ),
    )


def hardening_plan_to_runtime(
    plan: HardeningPlan,
) -> dict:
    """
    Convert a HardeningPlan into variables suitable
    for passing directly to an Ansible playbook.
    """

    control_metadata = {}

    for control in (
        plan.applicable_controls
    ):

        control_metadata[
            control.id
        ] = {
            "title": (
                control.title
            ),

            "assessment": (
                control.assessment
            ),

            "crucible_implementation": (
                control
                .crucible_implementation
            ),

            "tags": list(
                control.tags
            ),
        }

    return {
        "benchmark": {
            "id": (
                plan.benchmark.id
            ),

            "display_name": (
                plan.benchmark
                .display_name
            ),

            "authority": (
                plan.benchmark.authority
            ),

            "version": (
                plan.benchmark
                .benchmark_version
            ),
        },

        "profile": {
            "id": (
                plan.profile.id
            ),

            "display_name": (
                plan.profile
                .display_name
            ),
        },

        "controls": {
            "applicable": [
                control.id

                for control
                in plan.applicable_controls
            ],

            "automated": list(
                plan
                .automated_control_ids
            ),

            "manual": list(
                plan
                .manual_control_ids
            ),

            "not_implemented": list(
                plan
                .not_implemented_control_ids
            ),

            "exceptions": list(
                plan
                .exception_control_ids
            ),

            "metadata": (
                control_metadata
            ),
        },

        "counts": {
            "applicable": len(
                plan
                .applicable_controls
            ),

            "automated": len(
                plan
                .automated_control_ids
            ),

            "manual": len(
                plan
                .manual_control_ids
            ),

            "not_implemented": len(
                plan
                .not_implemented_control_ids
            ),

            "exceptions": len(
                plan
                .exception_control_ids
            ),
        },
    }