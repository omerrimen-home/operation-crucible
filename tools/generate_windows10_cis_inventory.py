from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

import yaml


BENCHMARK_ID = (
    "cis-microsoft-windows-10-standalone"
)

BENCHMARK_VERSION = "4.0.0"


# ============================================================
# Expected source-benchmark inventory
# ============================================================

EXPECTED_CONTROL_COUNT = 494

EXPECTED_SOURCE_PROFILE_COUNTS = {
    "L1": 333,
    "L2": 104,
    "BL": 44,
    "NG": 13,
}

EXPECTED_ASSESSMENT_COUNTS = {
    "automated": 492,
    "manual": 2,
}


# ============================================================
# PDF extraction
#
# PDF pages 3-27 contain the benchmark Table of Contents.
#
# For this benchmark version, the TOC is materially easier to
# parse than the Summary Table because long numeric control IDs
# in the Summary Table can wrap across lines.
#
# Example:
#
#   18.10.10.2.1
#   0
#
# actually represents:
#
#   18.10.10.2.10
#
# The TOC preserves those IDs correctly.
# ============================================================

TOC_FIRST_PDF_PAGE = 3

TOC_LAST_PDF_PAGE = 27


RECOMMENDATION_START = re.compile(
    r"^\s*"
    r"(?P<control>\d+(?:\.\d+)+)"
    r"\s+"
    r"\((?P<source_profile>L1|L2|BL|NG)\)"
    r"\s+"
    r"(?P<text>.*)$"
)


ASSESSMENT_PATTERN = re.compile(
    r"\((Automated|Manual)\)"
)


# ============================================================
# Effective Crucible profile membership
#
# CIS defines:
#
#   L2 extends L1
#
# and:
#
#   BitLocker
#   Next Generation
#
# as optional add-on recommendation sets.
#
# Therefore a source L1 recommendation belongs to every
# baseline profile, including L2 profiles.
#
# A source BL recommendation belongs only to BL-bearing
# profiles plus the standalone BL add-on profile.
#
# A source NG recommendation behaves equivalently.
# ============================================================

PROFILE_MEMBERSHIP = {

    "L1": [

        "level1",

        "level1-bitlocker",

        "level1-next-generation",

        "level1-bitlocker-next-generation",

        "level2",

        "level2-bitlocker",

        "level2-next-generation",

        "level2-bitlocker-next-generation",
    ],


    "L2": [

        "level2",

        "level2-bitlocker",

        "level2-next-generation",

        "level2-bitlocker-next-generation",
    ],


    "BL": [

        "bitlocker",

        "level1-bitlocker",

        "level1-bitlocker-next-generation",

        "level2-bitlocker",

        "level2-bitlocker-next-generation",
    ],


    "NG": [

        "next-generation",

        "level1-next-generation",

        "level1-bitlocker-next-generation",

        "level2-next-generation",

        "level2-bitlocker-next-generation",
    ],
}


SOURCE_PROFILE_TAG = {

    "L1": (
        "source-profile:level1"
    ),

    "L2": (
        "source-profile:level2"
    ),

    "BL": (
        "source-profile:bitlocker"
    ),

    "NG": (
        "source-profile:next-generation"
    ),
}


# ============================================================
# High-level implementation areas
#
# The Windows benchmark contains many structural headings with
# no recommendations underneath them.
#
# Actual recommendations in v4.0.0 occur in these top-level
# sections.
# ============================================================

AREA_BY_SECTION = {

    "1": (
        "account-policies"
    ),

    "2": (
        "local-policies"
    ),

    "5": (
        "system-services"
    ),

    "9": (
        "windows-defender-firewall"
    ),

    "17": (
        "advanced-audit-policy"
    ),

    "18": (
        "administrative-templates-computer"
    ),

    "19": (
        "administrative-templates-user"
    ),
}


# ============================================================
# Crucible-management-sensitive controls
#
# These L2 recommendations can destroy Crucible's PSRP/WinRM
# control channel.
#
# They remain legitimate CIS recommendations. We therefore do
# not delete them or pretend they are satisfied elsewhere.
#
# Instead the planner may derive a documented exception when
# the machine declares the semantic capability:
#
#   management:winrm
# ============================================================

MANAGEMENT_SENSITIVE_CONTROLS = {

    # Disable Windows Remote Management service.
    "5.41",

    # Disable remote server management through WinRM.
    "18.10.89.2.2",

    # Disable Windows Remote Shell access.
    "18.10.90.1",
}


HEADER = """# Operation Crucible hardening control inventory
#
# Source benchmark:
#   CIS Microsoft Windows 10 Stand-alone Benchmark
#   v4.0.0 - 2025-06-24
#
# This file stores recommendation metadata only.
#
# The source CIS Benchmark PDF is NOT stored in the Operation
# Crucible repository.
#
# BC-B inventory policy:
#
# - `assessment` preserves the source benchmark's
#   Automated/Manual assessment status.
#
# - Automated recommendations begin as `not_implemented`
#   until a later BC implementation milestone adds and
#   validates remediation.
#
# - Manual recommendations begin as `manual`.
#
# - Windows profile membership below is EFFECTIVE membership:
#
#       Level 2 extends Level 1.
#
#       BitLocker and Next Generation are optional add-ons.
#
# - `source-profile:*` preserves the profile marker appearing
#   in the source recommendation: L1, L2, BL, or NG.
#
# - `wave:deferred`, `risk:unreviewed`, and
#   `implementation-pending` are Operation Crucible
#   engineering metadata. They are not CIS metadata.
#
# - WinRM / Remote Shell recommendations that would sever the
#   Crucible PSRP management plane carry:
#
#       preserve-if-capability:management:winrm
#
#   This allows the planner to record an explicit derived
#   exception instead of silently destroying management
#   connectivity.
#
"""


def _normalize_title(
    text: str,
) -> str:

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _extract_toc_text(
    pdf_path: Path,
) -> str:

    pdftotext = shutil.which(
        "pdftotext"
    )

    if pdftotext is None:

        raise RuntimeError(
            "pdftotext was not found. "
            "Install poppler-utils on the controller."
        )

    with tempfile.TemporaryDirectory(
        prefix="crucible-win10-cis-"
    ) as temp_directory:

        output_path = (
            Path(
                temp_directory
            )
            /
            "toc.txt"
        )

        result = subprocess.run(
            [
                pdftotext,

                "-f",
                str(
                    TOC_FIRST_PDF_PAGE
                ),

                "-l",
                str(
                    TOC_LAST_PDF_PAGE
                ),

                "-layout",

                str(
                    pdf_path
                ),

                str(
                    output_path
                ),
            ],

            text=True,

            capture_output=True,

            check=False,
        )

        if result.returncode != 0:

            raise RuntimeError(
                "pdftotext failed:\n"
                +
                result.stderr.strip()
            )

        return output_path.read_text(
            encoding="utf-8",

            errors="replace",
        )


def _parse_recommendations(
    toc_text: str,
) -> list[
    dict[str, str]
]:

    lines = toc_text.splitlines()

    recommendations: list[
        dict[str, str]
    ] = []

    index = 0


    while index < len(
        lines
    ):

        match = (
            RECOMMENDATION_START.match(
                lines[
                    index
                ]
            )
        )

        if match is None:

            index += 1

            continue


        control_id = (
            match.group(
                "control"
            )
        )

        source_profile = (
            match.group(
                "source_profile"
            )
        )

        fragments = [

            match.group(
                "text"
            ).strip()
        ]


        cursor = (
            index
            +
            1
        )


        # ----------------------------------------------------
        # Recommendation titles frequently wrap over multiple
        # TOC lines.
        #
        # Accumulate until the source assessment marker appears.
        # ----------------------------------------------------

        while (

            cursor
            <
            len(
                lines
            )

            and

            ASSESSMENT_PATTERN.search(
                " ".join(
                    fragments
                )
            )
            is None

        ):

            if (
                RECOMMENDATION_START.match(
                    lines[
                        cursor
                    ]
                )
                is not None
            ):

                break


            fragments.append(
                lines[
                    cursor
                ].strip()
            )

            cursor += 1


        combined = (
            _normalize_title(
                " ".join(
                    fragments
                )
            )
        )


        assessment_match = (
            ASSESSMENT_PATTERN.search(
                combined
            )
        )


        if assessment_match is None:

            raise RuntimeError(
                "Could not resolve assessment "
                f"for control {control_id}: "
                f"{combined}"
            )


        title = (
            _normalize_title(
                combined[
                    :
                    assessment_match.start()
                ]
            )
        )


        assessment = (
            assessment_match
            .group(
                1
            )
            .lower()
        )


        recommendations.append(
            {
                "id": (
                    control_id
                ),

                "source_profile": (
                    source_profile
                ),

                "title": (
                    title
                ),

                "assessment": (
                    assessment
                ),
            }
        )


        index = cursor


    return recommendations


def _validate_recommendations(
    recommendations: list[
        dict[str, str]
    ],
) -> None:

    ids = [

        recommendation[
            "id"
        ]

        for recommendation
        in recommendations
    ]


    duplicates = sorted(

        control_id

        for (
            control_id,
            count,
        )
        in Counter(
            ids
        ).items()

        if count > 1
    )


    if duplicates:

        raise RuntimeError(
            "Duplicate control IDs extracted: "
            +
            ", ".join(
                duplicates
            )
        )


    if (
        len(
            recommendations
        )
        !=
        EXPECTED_CONTROL_COUNT
    ):

        raise RuntimeError(
            "Unexpected recommendation count. "
            f"Expected {EXPECTED_CONTROL_COUNT}, "
            f"found {len(recommendations)}."
        )


    profile_counts = Counter(

        recommendation[
            "source_profile"
        ]

        for recommendation
        in recommendations
    )


    if (
        dict(
            profile_counts
        )
        !=
        EXPECTED_SOURCE_PROFILE_COUNTS
    ):

        raise RuntimeError(
            "Unexpected source profile counts: "
            f"{dict(profile_counts)}"
        )


    assessment_counts = Counter(

        recommendation[
            "assessment"
        ]

        for recommendation
        in recommendations
    )


    if (
        dict(
            assessment_counts
        )
        !=
        EXPECTED_ASSESSMENT_COUNTS
    ):

        raise RuntimeError(
            "Unexpected assessment counts: "
            f"{dict(assessment_counts)}"
        )


def _area_for_control(
    control_id: str,
) -> str:

    section = (
        control_id.split(
            ".",
            1,
        )[
            0
        ]
    )


    try:

        return AREA_BY_SECTION[
            section
        ]


    except KeyError as exc:

        raise RuntimeError(
            "Recommendation appeared in an "
            "unexpected top-level benchmark "
            f"section: {control_id}"
        ) from exc


def _control_entry(
    recommendation: dict[
        str,
        str
    ],
) -> dict[
    str,
    Any
]:

    control_id = (
        recommendation[
            "id"
        ]
    )

    source_profile = (
        recommendation[
            "source_profile"
        ]
    )

    assessment = (
        recommendation[
            "assessment"
        ]
    )


    # --------------------------------------------------------
    # BC-B describes current Crucible implementation state,
    # not theoretical automability.
    #
    # CIS Automated:
    #
    #   Source says this can be assessed automatically.
    #
    # Crucible not_implemented:
    #
    #   We have not yet written the BC remediation/audit code.
    #
    # These concepts must remain separate.
    # --------------------------------------------------------

    if assessment == "manual":

        implementation = (
            "manual"
        )

        implementation_tag = (
            "manual-validation"
        )


    else:

        implementation = (
            "not_implemented"
        )

        implementation_tag = (
            "implementation-pending"
        )


    tags = [

        (
            "area:"
            +
            _area_for_control(
                control_id
            )
        ),

        "risk:unreviewed",

        "wave:deferred",

        SOURCE_PROFILE_TAG[
            source_profile
        ],

        implementation_tag,
    ]


    if (
        control_id
        in
        MANAGEMENT_SENSITIVE_CONTROLS
    ):

        tags.extend(
            [
                "management-sensitive",

                (
                    "preserve-if-capability:"
                    "management:winrm"
                ),
            ]
        )


    return {

        "title": (
            recommendation[
                "title"
            ]
        ),

        "profiles": list(
            PROFILE_MEMBERSHIP[
                source_profile
            ]
        ),

        "assessment": (
            assessment
        ),

        "crucible_implementation": (
            implementation
        ),

        "tags": (
            tags
        ),
    }


def build_inventory(
    pdf_path: Path,
) -> dict[
    str,
    Any
]:

    toc_text = (
        _extract_toc_text(
            pdf_path
        )
    )


    recommendations = (
        _parse_recommendations(
            toc_text
        )
    )


    _validate_recommendations(
        recommendations
    )


    controls: dict[
        str,
        dict[str, Any]
    ] = {}


    for recommendation in recommendations:

        controls[
            recommendation[
                "id"
            ]
        ] = (
            _control_entry(
                recommendation
            )
        )


    return {

        "schema_version": 1,

        "benchmark_id": (
            BENCHMARK_ID
        ),

        "benchmark_version": (
            BENCHMARK_VERSION
        ),

        "controls": (
            controls
        ),
    }


def write_inventory(
    output_path: Path,

    inventory: dict[
        str,
        Any
    ],
) -> None:

    output_path.parent.mkdir(
        parents=True,

        exist_ok=True,
    )


    yaml_text = (
        yaml.safe_dump(
            inventory,

            sort_keys=False,

            allow_unicode=True,

            default_flow_style=False,

            width=1000,
        )
    )


    output_path.write_text(
        HEADER
        +
        yaml_text,

        encoding="utf-8",
    )


def main() -> int:

    parser = argparse.ArgumentParser(

        description=(
            "Generate Operation Crucible's CIS "
            "Windows 10 Stand-alone recommendation "
            "inventory from a locally held CIS PDF."
        )
    )


    parser.add_argument(

        "pdf",

        type=Path,

        help=(
            "Path to CIS Microsoft Windows 10 "
            "Stand-alone Benchmark v4.0.0 PDF."
        ),
    )


    parser.add_argument(

        "--output",

        type=Path,

        default=(

            Path(
                "hardening"
            )

            /
            "benchmarks"

            /
            (
                "cis-microsoft-windows-10-"
                "standalone.yml"
            )
        ),

        help=(
            "Generated benchmark inventory path."
        ),
    )


    args = parser.parse_args()


    pdf_path = (
        args.pdf.resolve()
    )


    if not pdf_path.is_file():

        raise SystemExit(
            "Benchmark PDF not found: "
            f"{pdf_path}"
        )


    inventory = (
        build_inventory(
            pdf_path
        )
    )


    write_inventory(
        args.output,

        inventory,
    )


    controls = (
        inventory[
            "controls"
        ]
    )


    print()

    print(
        "Generated Windows 10 CIS inventory."
    )

    print(
        f"  Benchmark: {BENCHMARK_ID}"
    )

    print(
        f"  Version:   {BENCHMARK_VERSION}"
    )

    print(
        f"  Controls:  {len(controls)}"
    )

    print(
        f"  Output:    {args.output}"
    )

    print()


    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )