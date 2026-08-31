from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re

import yaml


BENCHMARK_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9._-]{0,127}$"
)

PROFILE_ID_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9._-]{0,127}$"
)

CONTROL_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)


BENCHMARK_STATUSES = {
    "planned",
    "implemented",
}

TARGET_TYPES = {
    "os",
    "service",
}

ASSESSMENT_TYPES = {
    "automated",
    "manual",
}

CONTROL_IMPLEMENTATION_TYPES = {
    "automated",
    "conditional",
    "audit_only",
    "satisfied_elsewhere",
    "manual",
    "not_implemented",
}


class HardeningCatalogError(
    ValueError
):
    """
    Raised when hardening benchmark metadata or
    benchmark control data is invalid.
    """


@dataclass(
    frozen=True
)
class HardeningProfileDefinition:
    """
    One profile exposed by a security benchmark.

    A benchmark profile is separate from a Crucible
    OS profile.

    Example:

        Crucible OS profile:
            ubuntu-26.04-server

        CIS benchmark profile:
            level1-server
    """

    id: str

    display_name: str

    description: str

    applies_to_profiles: tuple[
        str,
        ...
    ]

    default_for_profiles: tuple[
        str,
        ...
    ]


@dataclass(
    frozen=True
)
class HardeningBenchmarkDefinition:
    """
    Metadata describing one security benchmark.
    """

    id: str

    display_name: str

    description: str

    authority: str

    benchmark_version: str

    status: str

    target_type: str

    supported_profiles: tuple[
        str,
        ...
    ]

    profiles: dict[
        str,
        HardeningProfileDefinition
    ]

    controls_path: (
        Path
        | None
    )


@dataclass(
    frozen=True
)
class HardeningControlDefinition:
    """
    One control/recommendation from a benchmark.

    assessment describes how the source benchmark
    classifies the control.

    crucible_implementation describes what Crucible
    can currently do with it.

    These are deliberately separate.

    A source benchmark may call a control "Manual"
    while Crucible may eventually automate part or
    all of its enforcement.
    """

    id: str

    title: str

    profiles: tuple[
        str,
        ...
    ]

    assessment: str

    crucible_implementation: str

    tags: tuple[
        str,
        ...
    ]


@dataclass(
    frozen=True
)
class HardeningCatalog:
    """
    Parsed hardening benchmark registry.
    """

    schema_version: int

    definitions: dict[
        str,
        HardeningBenchmarkDefinition
    ]

    repo_root: Path


    def get(
        self,
        benchmark_id: str,
    ) -> HardeningBenchmarkDefinition:

        try:
            return self.definitions[
                benchmark_id
            ]

        except KeyError as exc:
            raise HardeningCatalogError(
                "Unknown hardening benchmark: "
                f"{benchmark_id}"
            ) from exc


def _load_yaml_mapping(
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
        raise HardeningCatalogError(
            f"Expected YAML mapping: {path}"
        )

    return data


def _parse_string_list(
    value: Any,
    *,
    field_name: str,
) -> tuple[str, ...]:

    if value is None:
        return ()

    if not isinstance(
        value,
        list,
    ):
        raise HardeningCatalogError(
            f"{field_name} must be a list."
        )

    resolved: list[str] = []

    seen: set[str] = set()

    for raw_value in value:

        item = str(
            raw_value
        ).strip()

        if not item:
            raise HardeningCatalogError(
                f"{field_name} contains "
                "an empty value."
            )

        if item in seen:
            raise HardeningCatalogError(
                f"{field_name} contains "
                f"duplicate value '{item}'."
            )

        seen.add(
            item
        )

        resolved.append(
            item
        )

    return tuple(
        resolved
    )


def _parse_profiles(
    benchmark_id: str,
    value: Any,
) -> dict[
    str,
    HardeningProfileDefinition
]:

    if value is None:
        value = {}

    if not isinstance(
        value,
        dict,
    ):
        raise HardeningCatalogError(
            f"Benchmark '{benchmark_id}' "
            "profiles must be a mapping."
        )

    profiles: dict[
        str,
        HardeningProfileDefinition
    ] = {}

    for (
        raw_profile_id,
        raw_profile,
    ) in value.items():

        profile_id = str(
            raw_profile_id
        ).strip()

        if not (
            PROFILE_ID_PATTERN
            .fullmatch(
                profile_id
            )
        ):
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "contains invalid profile ID "
                f"{profile_id!r}."
            )

        if not isinstance(
            raw_profile,
            dict,
        ):
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                f"profile '{profile_id}' "
                "must be a mapping."
            )

        unknown = (
            set(
                raw_profile
            )
            -
            {
                "display_name",
                "description",
                "applies_to_profiles",
                "default_for_profiles",
            }
        )

        if unknown:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                f"profile '{profile_id}' "
                "contains unsupported field(s): "
                +
                ", ".join(
                    sorted(
                        unknown
                    )
                )
            )

        display_name = str(
            raw_profile.get(
                "display_name",
                "",
            )
        ).strip()

        if not display_name:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                f"profile '{profile_id}' "
                "requires display_name."
            )

        description = str(
            raw_profile.get(
                "description",
                "",
            )
        ).strip()

        applies_to_profiles = (
            _parse_string_list(
                raw_profile.get(
                    "applies_to_profiles",
                    [],
                ),
                field_name=(
                    f"{benchmark_id}."
                    f"{profile_id}."
                    "applies_to_profiles"
                ),
            )
        )

        default_for_profiles = (
            _parse_string_list(
                raw_profile.get(
                    "default_for_profiles",
                    [],
                ),
                field_name=(
                    f"{benchmark_id}."
                    f"{profile_id}."
                    "default_for_profiles"
                ),
            )
        )

        invalid_defaults = (
            set(
                default_for_profiles
            )
            -
            set(
                applies_to_profiles
            )
        )

        if invalid_defaults:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                f"profile '{profile_id}' "
                "contains default_for_profiles "
                "entries that are not also in "
                "applies_to_profiles: "
                +
                ", ".join(
                    sorted(
                        invalid_defaults
                    )
                )
            )

        profiles[
            profile_id
        ] = (
            HardeningProfileDefinition(
                id=profile_id,
                display_name=display_name,
                description=description,
                applies_to_profiles=(
                    applies_to_profiles
                ),
                default_for_profiles=(
                    default_for_profiles
                ),
            )
        )

    return profiles


def load_hardening_catalog(
    path: Path,
    *,
    repo_root: Path | None = None,
) -> HardeningCatalog:
    """
    Load config/hardening.yml.
    """

    data = _load_yaml_mapping(
        path
    )

    raw_schema_version = data.get(
        "schema_version",
        0,
    )

    if isinstance(
        raw_schema_version,
        bool,
    ):
        raise HardeningCatalogError(
            "hardening schema_version "
            "must be an integer."
        )

    try:
        schema_version = int(
            raw_schema_version
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        raise HardeningCatalogError(
            "hardening schema_version "
            "must be an integer."
        ) from exc

    if schema_version != 1:
        raise HardeningCatalogError(
            "Unsupported hardening "
            "schema_version: "
            f"{schema_version}"
        )

    raw_benchmarks = data.get(
        "benchmarks"
    )

    if (
        not isinstance(
            raw_benchmarks,
            dict,
        )
        or
        not raw_benchmarks
    ):
        raise HardeningCatalogError(
            "Hardening catalog requires "
            "a non-empty benchmarks mapping."
        )

    if repo_root is None:
        repo_root = (
            path.resolve()
            .parents[1]
        )

    repo_root = (
        repo_root.resolve()
    )

    definitions: dict[
        str,
        HardeningBenchmarkDefinition
    ] = {}

    for (
        raw_benchmark_id,
        raw_benchmark,
    ) in raw_benchmarks.items():

        benchmark_id = str(
            raw_benchmark_id
        ).strip()

        if not (
            BENCHMARK_ID_PATTERN
            .fullmatch(
                benchmark_id
            )
        ):
            raise HardeningCatalogError(
                "Invalid benchmark ID: "
                f"{benchmark_id!r}"
            )

        if not isinstance(
            raw_benchmark,
            dict,
        ):
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "must be a mapping."
            )

        unknown = (
            set(
                raw_benchmark
            )
            -
            {
                "display_name",
                "description",
                "authority",
                "benchmark_version",
                "status",
                "target",
                "profiles",
                "controls_file",
            }
        )

        if unknown:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "contains unsupported field(s): "
                +
                ", ".join(
                    sorted(
                        unknown
                    )
                )
            )

        display_name = str(
            raw_benchmark.get(
                "display_name",
                "",
            )
        ).strip()

        if not display_name:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "requires display_name."
            )

        description = str(
            raw_benchmark.get(
                "description",
                "",
            )
        ).strip()

        if not description:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "requires description."
            )

        authority = str(
            raw_benchmark.get(
                "authority",
                "",
            )
        ).strip()

        if not authority:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "requires authority."
            )

        benchmark_version = str(
            raw_benchmark.get(
                "benchmark_version",
                "",
            )
        ).strip()

        if not benchmark_version:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "requires benchmark_version."
            )

        status = str(
            raw_benchmark.get(
                "status",
                "",
            )
        ).strip().lower()

        if (
            status
            not in BENCHMARK_STATUSES
        ):
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "status must be one of: "
                +
                ", ".join(
                    sorted(
                        BENCHMARK_STATUSES
                    )
                )
            )

        target = raw_benchmark.get(
            "target",
            {},
        )

        if not isinstance(
            target,
            dict,
        ):
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "target must be a mapping."
            )

        unknown_target = (
            set(
                target
            )
            -
            {
                "type",
                "supported_profiles",
            }
        )

        if unknown_target:
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "contains unsupported target "
                "field(s): "
                +
                ", ".join(
                    sorted(
                        unknown_target
                    )
                )
            )

        target_type = str(
            target.get(
                "type",
                "",
            )
        ).strip().lower()

        if (
            target_type
            not in TARGET_TYPES
        ):
            raise HardeningCatalogError(
                f"Benchmark '{benchmark_id}' "
                "target.type must be one of: "
                +
                ", ".join(
                    sorted(
                        TARGET_TYPES
                    )
                )
            )

        supported_profiles = (
            _parse_string_list(
                target.get(
                    "supported_profiles",
                    [],
                ),
                field_name=(
                    f"{benchmark_id}."
                    "target.supported_profiles"
                ),
            )
        )

        if (
            target_type == "os"
            and
            not supported_profiles
        ):
            raise HardeningCatalogError(
                f"OS benchmark "
                f"'{benchmark_id}' "
                "requires at least one "
                "supported Crucible OS profile."
            )

        profiles = (
            _parse_profiles(
                benchmark_id,
                raw_benchmark.get(
                    "profiles",
                    {},
                ),
            )
        )

        raw_controls_file = (
            raw_benchmark.get(
                "controls_file"
            )
        )

        controls_path: (
            Path
            | None
        )

        if raw_controls_file is None:
            controls_path = None

        else:
            relative_controls_path = Path(
                str(
                    raw_controls_file
                ).strip()
            )

            if not str(
                relative_controls_path
            ):
                raise HardeningCatalogError(
                    f"Benchmark '{benchmark_id}' "
                    "controls_file may not "
                    "be empty."
                )

            controls_path = (
                repo_root
                / relative_controls_path
            ).resolve()

            try:
                controls_path.relative_to(
                    repo_root
                )

            except ValueError as exc:
                raise HardeningCatalogError(
                    f"Benchmark '{benchmark_id}' "
                    "controls_file escapes "
                    "repository root."
                ) from exc

        if status == "implemented":

            if not profiles:
                raise HardeningCatalogError(
                    f"Implemented benchmark "
                    f"'{benchmark_id}' "
                    "requires at least "
                    "one benchmark profile."
                )

            if controls_path is None:
                raise HardeningCatalogError(
                    f"Implemented benchmark "
                    f"'{benchmark_id}' "
                    "requires controls_file."
                )

            if not controls_path.is_file():
                raise HardeningCatalogError(
                    f"Benchmark "
                    f"'{benchmark_id}' "
                    "controls file not found: "
                    f"{controls_path}"
                )

        definitions[
            benchmark_id
        ] = (
            HardeningBenchmarkDefinition(
                id=benchmark_id,
                display_name=display_name,
                description=description,
                authority=authority,
                benchmark_version=(
                    benchmark_version
                ),
                status=status,
                target_type=target_type,
                supported_profiles=(
                    supported_profiles
                ),
                profiles=profiles,
                controls_path=(
                    controls_path
                ),
            )
        )

    return HardeningCatalog(
        schema_version=(
            schema_version
        ),
        definitions=(
            definitions
        ),
        repo_root=(
            repo_root
        ),
    )


def load_benchmark_controls(
    benchmark: HardeningBenchmarkDefinition,
) -> tuple[
    HardeningControlDefinition,
    ...
]:
    """
    Load the individual controls belonging to one
    implemented benchmark.
    """

    if benchmark.status != "implemented":
        raise HardeningCatalogError(
            f"Benchmark '{benchmark.id}' "
            "is not implemented."
        )

    if benchmark.controls_path is None:
        raise HardeningCatalogError(
            f"Benchmark '{benchmark.id}' "
            "has no controls file."
        )

    data = _load_yaml_mapping(
        benchmark.controls_path
    )

    if data.get(
        "schema_version"
    ) != 1:
        raise HardeningCatalogError(
            f"Controls file for "
            f"'{benchmark.id}' "
            "requires schema_version 1."
        )

    control_benchmark_id = str(
        data.get(
            "benchmark_id",
            "",
        )
    ).strip()

    if (
        control_benchmark_id
        != benchmark.id
    ):
        raise HardeningCatalogError(
            "Controls file benchmark_id "
            f"'{control_benchmark_id}' "
            "does not match "
            f"'{benchmark.id}'."
        )

    control_version = str(
        data.get(
            "benchmark_version",
            "",
        )
    ).strip()

    if (
        control_version
        != benchmark.benchmark_version
    ):
        raise HardeningCatalogError(
            f"Controls file for "
            f"'{benchmark.id}' "
            "targets benchmark version "
            f"'{control_version}', expected "
            f"'{benchmark.benchmark_version}'."
        )

    raw_controls = data.get(
        "controls"
    )

    if (
        not isinstance(
            raw_controls,
            dict,
        )
        or
        not raw_controls
    ):
        raise HardeningCatalogError(
            f"Benchmark '{benchmark.id}' "
            "requires a non-empty "
            "controls mapping."
        )

    controls: list[
        HardeningControlDefinition
    ] = []

    for (
        raw_control_id,
        raw_control,
    ) in raw_controls.items():

        control_id = str(
            raw_control_id
        ).strip()

        if not (
            CONTROL_ID_PATTERN
            .fullmatch(
                control_id
            )
        ):
            raise HardeningCatalogError(
                f"Benchmark '{benchmark.id}' "
                "contains invalid control ID "
                f"{control_id!r}."
            )

        if not isinstance(
            raw_control,
            dict,
        ):
            raise HardeningCatalogError(
                f"Control '{control_id}' "
                "must be a mapping."
            )

        unknown = (
            set(
                raw_control
            )
            -
            {
                "title",
                "profiles",
                "assessment",
                "crucible_implementation",
                "tags",
            }
        )

        if unknown:
            raise HardeningCatalogError(
                f"Control '{control_id}' "
                "contains unsupported field(s): "
                +
                ", ".join(
                    sorted(
                        unknown
                    )
                )
            )

        title = str(
            raw_control.get(
                "title",
                "",
            )
        ).strip()

        if not title:
            raise HardeningCatalogError(
                f"Control '{control_id}' "
                "requires title."
            )

        profiles = (
            _parse_string_list(
                raw_control.get(
                    "profiles",
                    [],
                ),
                field_name=(
                    f"{benchmark.id}."
                    f"{control_id}.profiles"
                ),
            )
        )

        if not profiles:
            raise HardeningCatalogError(
                f"Control '{control_id}' "
                "must belong to at least "
                "one benchmark profile."
            )

        unknown_profiles = (
            set(
                profiles
            )
            -
            set(
                benchmark.profiles
            )
        )

        if unknown_profiles:
            raise HardeningCatalogError(
                f"Control '{control_id}' "
                "references unknown benchmark "
                "profile(s): "
                +
                ", ".join(
                    sorted(
                        unknown_profiles
                    )
                )
            )

        assessment = str(
            raw_control.get(
                "assessment",
                "",
            )
        ).strip().lower()

        if (
            assessment
            not in ASSESSMENT_TYPES
        ):
            raise HardeningCatalogError(
                f"Control '{control_id}' "
                "assessment must be one of: "
                +
                ", ".join(
                    sorted(
                        ASSESSMENT_TYPES
                    )
                )
            )

        crucible_implementation = str(
            raw_control.get(
                "crucible_implementation",
                "",
            )
        ).strip().lower()

        if (
            crucible_implementation
            not in
            CONTROL_IMPLEMENTATION_TYPES
        ):
            raise HardeningCatalogError(
                f"Control '{control_id}' "
                "crucible_implementation "
                "must be one of: "
                +
                ", ".join(
                    sorted(
                        CONTROL_IMPLEMENTATION_TYPES
                    )
                )
            )

        tags = (
            _parse_string_list(
                raw_control.get(
                    "tags",
                    [],
                ),
                field_name=(
                    f"{benchmark.id}."
                    f"{control_id}.tags"
                ),
            )
        )

        controls.append(
            HardeningControlDefinition(
                id=control_id,
                title=title,
                profiles=profiles,
                assessment=assessment,
                crucible_implementation=(
                    crucible_implementation
                ),
                tags=tags,
            )
        )

    return tuple(
        controls
    )