#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from implement_windows10_cis_bc_g import (
    classification_counts,
    extract_pdf_text,
    generate_registry_inventory,
    source_profile,
    write_yaml,
)


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


BENCHMARK_PATH = (
    REPO_ROOT
    / "hardening"
    / "benchmarks"
    / "cis-microsoft-windows-10-standalone.yml"
)


OUTPUT_POLICY_PATH = (
    REPO_ROOT
    / "ansible"
    / "roles"
    / "crucible_cis_windows_10_standalone"
    / "vars"
    / "advanced_profiles.yml"
)


UNRESOLVED_PATH = (
    REPO_ROOT
    / ".crucible"
    / "generated"
    / "windows10-cis-bc-h-unresolved.yml"
)


# ============================================================
# BC-G expected starting state
# ============================================================

EXPECTED_PRE_BC_H = {

    "automated": 429,

    "conditional": 5,

    "audit_only": 1,

    "manual": 2,

    "not_implemented": 57,
}


# ============================================================
# CIS profile-extension counts
# ============================================================

EXPECTED_BITLOCKER_CONTROLS = 44

EXPECTED_NEXT_GENERATION_CONTROLS = 13

EXPECTED_ADVANCED_CONTROLS = 57


# ============================================================
# BC-H expected final state
#
# The remaining BL/NG recommendations are source-Automated
# and Crucible implements their benchmark policy state
# declaratively.
#
# Hardware/runtime capability is reported separately.
# ============================================================

EXPECTED_POST_BC_H = {

    "automated": 486,

    "conditional": 5,

    "audit_only": 1,

    "manual": 2,

    "not_implemented": 0,
}


def load_yaml(
    path: Path,
) -> dict[str, Any]:

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

        raise RuntimeError(
            f"{path} is not a YAML mapping."
        )


    return data


def validate_counts(
    counts: Counter[str],
    expected: dict[str, int],
    *,
    stage: str,
) -> None:

    for (
        classification,
        expected_count,
    ) in expected.items():

        actual = counts.get(
            classification,
            0,
        )


        if (
            actual
            !=
            expected_count
        ):

            raise RuntimeError(
                f"{stage}: expected "
                f"{expected_count} "
                f"{classification} controls, "
                f"found {actual}."
            )


    if (
        sum(
            counts.values()
        )
        !=
        494
    ):

        raise RuntimeError(
            f"{stage}: classification total "
            "does not equal 494."
        )


def clean_engineering_tags(
    tags: list[str],
) -> list[str]:

    prefixes = (
        "risk:",
        "wave:",
    )


    remove_exact = {
        "implementation-pending",
    }


    return [

        tag

        for tag
        in tags

        if (
            tag
            not in
            remove_exact
        )

        and

        not any(
            tag.startswith(
                prefix
            )
            for prefix
            in prefixes
        )
    ]


def add_unique(
    tags: list[str],
    *new_tags: str,
) -> list[str]:

    result = list(
        tags
    )


    for tag in new_tags:

        if (
            tag
            not in
            result
        ):

            result.append(
                tag
            )


    return result


def promote_bitlocker_control(
    control_id: str,
    control: dict[str, Any],
) -> None:

    tags = clean_engineering_tags(
        list(
            control.get(
                "tags",
                [],
            )
        )
    )


    tags = add_unique(
        tags,

        "area:bitlocker",

        "risk:high",

        "wave:3",

        "backend:registry",

        "profile-addon:bitlocker",

        "encryption-policy",

        "generated-from:cis-audit-registry-backing",

        "reviewed:bc-h",
    )


    # --------------------------------------------------------
    # A handful of BL controls are specifically intended to
    # reduce DMA / physical-device attack paths.
    # --------------------------------------------------------

    if (
        control_id.startswith(
            "18.9.7.1."
        )
    ):

        tags = add_unique(
            tags,

            "physical-device-security",

            "device-installation-restriction",
        )


    if (
        control_id.startswith(
            "18.10.10."
        )
    ):

        tags = add_unique(
            tags,

            "bitlocker-drive-policy",
        )


    control[
        "crucible_implementation"
    ] = "automated"

    control[
        "tags"
    ] = tags


def promote_next_generation_control(
    control_id: str,
    control: dict[str, Any],
) -> None:

    tags = clean_engineering_tags(
        list(
            control.get(
                "tags",
                [],
            )
        )
    )


    tags = add_unique(
        tags,

        "area:next-generation-security",

        "risk:high",

        "wave:3",

        "backend:registry",

        "profile-addon:next-generation",

        "hardware-sensitive",

        "advanced-virtualization-security",

        "generated-from:cis-audit-registry-backing",

        "reviewed:bc-h",
    )


    # --------------------------------------------------------
    # Device Guard / VBS
    # --------------------------------------------------------

    if (
        control_id.startswith(
            "18.9.5."
        )
    ):

        tags = add_unique(
            tags,

            "virtualization-based-security",

            "uefi-sensitive",

            "secure-boot-sensitive",
        )


    # --------------------------------------------------------
    # LSA protection
    # --------------------------------------------------------

    if (
        control_id
        ==
        "18.9.26.2"
    ):

        tags = add_unique(
            tags,

            "lsass-protection",

            "uefi-lock",
        )


    # --------------------------------------------------------
    # Microsoft Defender Application Guard
    # --------------------------------------------------------

    if (
        control_id.startswith(
            "18.10.44."
        )
    ):

        tags = add_unique(
            tags,

            "application-guard",

            "virtualization-required",
        )


    control[
        "crucible_implementation"
    ] = "automated"

    control[
        "tags"
    ] = tags


def main() -> int:

    parser = argparse.ArgumentParser(

        description=(
            "Implement Operation Crucible Windows 10 "
            "CIS milestone BC-H."
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


    args = parser.parse_args()


    pdf_path = (
        args.pdf
        .expanduser()
        .resolve()
    )


    if (
        not pdf_path.is_file()
    ):

        raise SystemExit(
            "Benchmark PDF not found: "
            f"{pdf_path}"
        )


    benchmark = load_yaml(
        BENCHMARK_PATH
    )


    controls = benchmark.get(
        "controls"
    )


    if not isinstance(
        controls,
        dict,
    ):

        raise RuntimeError(
            "Benchmark contains no controls mapping."
        )


    # ========================================================
    # Validate exact BC-G starting state.
    # ========================================================

    pre_counts = classification_counts(
        controls
    )


    validate_counts(
        pre_counts,

        EXPECTED_PRE_BC_H,

        stage=(
            "BC-G starting state"
        ),
    )


    remaining = {

        str(
            control_id
        ):
            control

        for (
            control_id,
            control,
        )
        in controls.items()

        if (
            control.get(
                "crucible_implementation"
            )
            ==
            "not_implemented"
        )
    }


    if (
        len(
            remaining
        )
        !=
        EXPECTED_ADVANCED_CONTROLS
    ):

        raise RuntimeError(
            "Expected exactly "
            f"{EXPECTED_ADVANCED_CONTROLS} "
            "remaining BC-H controls, found "
            f"{len(remaining)}."
        )


    # ========================================================
    # Split by source profile.
    # ========================================================

    bitlocker_ids: set[str] = set()

    next_generation_ids: set[str] = set()


    for (
        control_id,
        control,
    ) in remaining.items():

        profile = source_profile(
            control
        )


        if (
            profile
            ==
            "bitlocker"
        ):

            bitlocker_ids.add(
                control_id
            )


        elif (
            profile
            ==
            "next-generation"
        ):

            next_generation_ids.add(
                control_id
            )


        else:

            raise RuntimeError(
                "BC-H found a remaining control "
                "that is neither BitLocker nor "
                "Next Generation: "
                f"{control_id} "
                f"({profile})"
            )


    if (
        len(
            bitlocker_ids
        )
        !=
        EXPECTED_BITLOCKER_CONTROLS
    ):

        raise RuntimeError(
            "Expected "
            f"{EXPECTED_BITLOCKER_CONTROLS} "
            "BitLocker controls, found "
            f"{len(bitlocker_ids)}."
        )


    if (
        len(
            next_generation_ids
        )
        !=
        EXPECTED_NEXT_GENERATION_CONTROLS
    ):

        raise RuntimeError(
            "Expected "
            f"{EXPECTED_NEXT_GENERATION_CONTROLS} "
            "Next Generation controls, found "
            f"{len(next_generation_ids)}."
        )


    # ========================================================
    # Source assessment sanity.
    #
    # All 57 add-on recommendations in this benchmark are
    # Automated recommendations.
    # ========================================================

    for (
        control_id,
        control,
    ) in remaining.items():

        if (
            control.get(
                "assessment"
            )
            !=
            "automated"
        ):

            raise RuntimeError(
                "BC-H expected source-Automated "
                "recommendation but found another "
                f"assessment for {control_id}: "
                f"{control.get('assessment')}"
            )


    # ========================================================
    # Parse source PDF.
    #
    # Reuse the fail-closed BC-G parser.
    # ========================================================

    print(
        "Extracting CIS benchmark text..."
    )


    pdf_text = extract_pdf_text(
        pdf_path
    )


    print(
        "Resolving BC-H BitLocker / "
        "Next Generation registry policies..."
    )


    (
        machine_policies,
        user_policies,
        unresolved,
    ) = generate_registry_inventory(
        pdf_text,

        set(
            remaining
        ),
    )


    resolved_ids = {

        item[
            "control_id"
        ]

        for item
        in (
            machine_policies
            +
            user_policies
        )
    }


    missing_resolution = (
        set(
            remaining
        )
        -
        resolved_ids
    )


    if (
        unresolved
        or
        missing_resolution
    ):

        unresolved_payload = {

            "schema_version": 1,

            "milestone":
                "BC-H",

            "expected_controls":
                EXPECTED_ADVANCED_CONTROLS,

            "expected_bitlocker":
                EXPECTED_BITLOCKER_CONTROLS,

            "expected_next_generation":
                EXPECTED_NEXT_GENERATION_CONTROLS,

            "resolved_control_count":
                len(
                    resolved_ids
                ),

            "unresolved": {

                control_id: (
                    unresolved.get(
                        control_id,

                        "No generated registry "
                        "policy entry."
                    )
                )

                for control_id
                in sorted(
                    missing_resolution
                    |
                    set(
                        unresolved
                    )
                )
            },
        }


        write_yaml(
            UNRESOLVED_PATH,

            unresolved_payload,
        )


        raise RuntimeError(
            "BC-H registry extraction was incomplete. "
            "No benchmark classifications were changed.\n"
            f"Review: {UNRESOLVED_PATH}"
        )


    if (
        len(
            resolved_ids
        )
        !=
        EXPECTED_ADVANCED_CONTROLS
    ):

        raise RuntimeError(
            "BC-H resolved an unexpected number "
            "of controls."
        )


    # ========================================================
    # Split generated registry rows.
    #
    # A single CIS control can have multiple registry values,
    # so validate unique CONTROL IDs rather than row counts.
    # ========================================================

    bitlocker_machine = [

        entry

        for entry
        in machine_policies

        if (
            entry[
                "control_id"
            ]
            in
            bitlocker_ids
        )
    ]


    bitlocker_user = [

        entry

        for entry
        in user_policies

        if (
            entry[
                "control_id"
            ]
            in
            bitlocker_ids
        )
    ]


    next_generation_machine = [

        entry

        for entry
        in machine_policies

        if (
            entry[
                "control_id"
            ]
            in
            next_generation_ids
        )
    ]


    next_generation_user = [

        entry

        for entry
        in user_policies

        if (
            entry[
                "control_id"
            ]
            in
            next_generation_ids
        )
    ]


    generated_bitlocker_ids = {

        entry[
            "control_id"
        ]

        for entry
        in (
            bitlocker_machine
            +
            bitlocker_user
        )
    }


    generated_next_generation_ids = {

        entry[
            "control_id"
        ]

        for entry
        in (
            next_generation_machine
            +
            next_generation_user
        )
    }


    if (
        generated_bitlocker_ids
        !=
        bitlocker_ids
    ):

        raise RuntimeError(
            "Generated BitLocker inventory does "
            "not exactly match the 44 BL controls."
        )


    if (
        generated_next_generation_ids
        !=
        next_generation_ids
    ):

        raise RuntimeError(
            "Generated Next Generation inventory "
            "does not exactly match the 13 NG controls."
        )


    # ========================================================
    # Write generated policy inventory.
    # ========================================================

    policy_header = """# Operation Crucible
#
# Generated BC-H Windows 10 CIS advanced-profile policy
# inventory.
#
# SOURCE:
#   CIS Microsoft Windows 10 Stand-alone Benchmark v4.0.0
#
# This file contains the registry backing stated by the
# benchmark's Audit procedures for:
#
#   - BitLocker profile controls
#   - Next Generation profile controls
#
# IMPORTANT:
#
#   Setting BitLocker policy does not itself encrypt a drive.
#
#   Setting Next Generation policy does not guarantee that
#   the current virtual/physical hardware can activate VBS,
#   Credential Guard, Application Guard, or other hardware-
#   dependent runtime features.
#
# Do not hand-edit this generated file.
#
"""


    policy_data = {

        (
            "crucible_cis_windows_10_"
            "bitlocker_machine_registry_policies"
        ):
            bitlocker_machine,

        (
            "crucible_cis_windows_10_"
            "bitlocker_user_registry_policies"
        ):
            bitlocker_user,

        (
            "crucible_cis_windows_10_"
            "next_generation_machine_registry_policies"
        ):
            next_generation_machine,

        (
            "crucible_cis_windows_10_"
            "next_generation_user_registry_policies"
        ):
            next_generation_user,
    }


    write_yaml(
        OUTPUT_POLICY_PATH,

        policy_data,

        header=(
            policy_header
        ),
    )


    # ========================================================
    # Promote catalog controls only AFTER all source parsing
    # and inventory validation succeeds.
    # ========================================================

    for control_id in sorted(
        bitlocker_ids
    ):

        promote_bitlocker_control(
            control_id,

            controls[
                control_id
            ],
        )


    for control_id in sorted(
        next_generation_ids
    ):

        promote_next_generation_control(
            control_id,

            controls[
                control_id
            ],
        )


    # ========================================================
    # Final catalog invariants.
    # ========================================================

    post_counts = classification_counts(
        controls
    )


    validate_counts(
        post_counts,

        EXPECTED_POST_BC_H,

        stage=(
            "BC-H final state"
        ),
    )


    unimplemented = {

        control_id

        for (
            control_id,
            control,
        )
        in controls.items()

        if (
            control.get(
                "crucible_implementation"
            )
            ==
            "not_implemented"
        )
    }


    if unimplemented:

        raise RuntimeError(
            "BC-H unexpectedly left controls "
            "not implemented:\n"
            +
            "\n".join(
                sorted(
                    unimplemented
                )
            )
        )


    write_yaml(
        BENCHMARK_PATH,

        benchmark,
    )


    if (
        UNRESOLVED_PATH.exists()
    ):

        UNRESOLVED_PATH.unlink()


    print()
    print(
        "BC-H complete."
    )

    print(
        "  BitLocker controls:",
        len(
            bitlocker_ids
        ),
    )

    print(
        "  Next Generation controls:",
        len(
            next_generation_ids
        ),
    )

    print(
        "  Advanced controls:",
        len(
            remaining
        ),
    )

    print(
        "  Machine policy rows:",
        len(
            machine_policies
        ),
    )

    print(
        "  User policy rows:",
        len(
            user_policies
        ),
    )

    print()
    print(
        "Global classifications:"
    )


    for classification in (

        "automated",

        "conditional",

        "audit_only",

        "manual",

        "not_implemented",

    ):

        print(
            f"  {classification}: "
            f"{post_counts.get(classification, 0)}"
        )


    return 0


if __name__ == "__main__":

    raise SystemExit(
        main()
    )