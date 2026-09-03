#!/usr/bin/env python3

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
    / "administrative_templates.yml"
)


UNRESOLVED_PATH = (
    REPO_ROOT
    / ".crucible"
    / "generated"
    / "windows10-cis-bc-g-unresolved.yml"
)


# ============================================================
# Expected BC-F starting state
# ============================================================

EXPECTED_PRE_BC_G = {

    "automated": 190,

    "conditional": 2,

    "audit_only": 1,

    "manual": 2,

    "not_implemented": 299,
}


# ============================================================
# Expected BC-G scope
#
# 299 pending after BC-F
#
#   57  BL / NG add-on controls -> BC-H
#
# leaving:
#
#   242 standard L1 / L2 controls -> BC-G
#
# Of those:
#
#    26 L2 services
#   216 registry-backed policies
# ============================================================

EXPECTED_BC_G_TOTAL = 242

EXPECTED_BC_G_SERVICES = 26

EXPECTED_BC_G_REGISTRY_CONTROLS = 216

EXPECTED_REMAINING_ADDONS = 57


# ============================================================
# Post-BC-G global classification
# ============================================================

EXPECTED_POST_BC_G = {

    "automated": 429,

    "conditional": 5,

    "audit_only": 1,

    "manual": 2,

    "not_implemented": 57,
}


# ============================================================
# These recommendations would break Crucible's existing
# WinRM / PSRP management plane.
#
# They remain benchmark controls and become conditional.
#
# When management:winrm is present, the existing planner
# converts them into documented derived exceptions.
# ============================================================

MANAGEMENT_SENSITIVE_CONTROLS = {

    "5.41",

    "18.10.89.2.2",

    "18.10.90.1",
}


# ============================================================
# Explicit registry-policy overrides
#
# These are deliberately narrow exceptions for benchmark
# recommendations whose Audit text does not contain enough
# machine-readable information for the generic parser.
#
# Do NOT use this as a general fallback. Every entry must be
# individually justified and traceable.
# ============================================================

REGISTRY_POLICY_OVERRIDES: dict[
    str,
    list[
        dict[
            str,
            Any,
        ]
    ],
] = {

    # --------------------------------------------------------
    # CIS 18.10.16.8
    #
    # "Toggle user control over Insider builds"
    #
    # CIS v4.0.0 provides the registry location:
    #
    # HKEY_LOCAL_MACHINE
    #   \SOFTWARE
    #   \Policies
    #   \Microsoft
    #   \Windows
    #   \PreviewBuilds
    #   :AllowBuildPreview
    #
    # but does not state the registry type/value in the Audit
    # paragraph.
    #
    # Microsoft documents AllowBuildPreview as an integer:
    #
    #   0 = preview builds not allowed
    #   1 = preview builds allowed
    #   2 = not configured
    #
    # The CIS-prescribed state is Disabled, therefore Crucible
    # enforces DWORD 0.
    # --------------------------------------------------------

    "18.10.16.8": [

        {

            "control_id":
                "18.10.16.8",

            "path": (
                "HKLM:\\"
                "SOFTWARE\\"
                "Policies\\"
                "Microsoft\\"
                "Windows\\"
                "PreviewBuilds"
            ),

            "name":
                "AllowBuildPreview",

            "type":
                "dword",

            "data":
                0,

            "source_value_text": (
                "Explicit BC-G override: "
                "CIS v4.0.0 supplies the registry "
                "location but omits type/value; "
                "Microsoft System Policy CSP defines "
                "AllowBuildPreview=0 as not allowed."
            ),
        },
    ],
}

# ============================================================
# Recommendation detection
#
# TOC and Summary Table also contain strings like:
#
#   18.10.93.2.1 (L1)
#
# We therefore additionally require the resulting block to
# contain "Profile Applicability:" and "Audit:" before
# considering it the real recommendation body.
# ============================================================

RECOMMENDATION_START = re.compile(

    r"(?m)"
    r"^\s*"
    r"(?P<control>\d+(?:\.\d+)+)"
    r"\s+"
    r"\((?P<profile>L1|L2|BL|NG)\)"
    r"\s+"
)


REGISTRY_DESCRIPTOR = re.compile(

    r"REG_"
    r"(?P<type1>"
    r"DWORD|QWORD|SZ|EXPAND_SZ|MULTI_SZ"
    r")"

    r"(?:"
    r"\s+or\s+REG_"
    r"(?P<type2>"
    r"DWORD|QWORD|SZ|EXPAND_SZ|MULTI_SZ"
    r")"
    r")?"

    # --------------------------------------------------------
    # CIS normally uses:
    #
    #     REG_DWORD value of 1
    #
    # but some recommendations use alternate grammar such as:
    #
    #     REG_SZ that is <blank> i.e. no value set
    #
    # Both describe the registry backing for the policy.
    # --------------------------------------------------------

    r"\s+"
    r"(?:"
        r"value(?:s)?\s+of"
        r"|"
        r"that\s+is"
    r")"
    r"\s+"

    r"(?P<value>.+?)"

    r"(?="
        r"\.\s"
        r"|$"
    r")",

    re.IGNORECASE,
)


REGISTRY_ROOT = re.compile(

    r"^(?:"
    r"HKLM"
    r"|HKCU"
    r"|HKU"
    r"|HKEY_LOCAL_MACHINE"
    r"|HKEY_CURRENT_USER"
    r"|HKEY_USERS"
    r")\\",

    re.IGNORECASE,
)

REGISTRY_HIVE_ALIASES = {

    "HKLM":
        "HKLM",

    "HKEY_LOCAL_MACHINE":
        "HKLM",

    "HKCU":
        "HKCU",

    "HKEY_CURRENT_USER":
        "HKCU",

    "HKU":
        "HKU",

    "HKEY_USERS":
        "HKU",
}


STOP_LINE_PREFIXES = (

    "Remediation:",

    "Default Value:",

    "References:",

    "CIS Controls:",

    "Audit:",

    "Navigate to",

    "This group policy",

    "This policy setting",

    "32-bit subsystem",

    "64-bit subsystem",
)


# ============================================================
# Basic YAML helpers
# ============================================================

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


def write_yaml(
    path: Path,
    data: dict[str, Any],
    *,
    header: str = "",
) -> None:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    rendered = yaml.safe_dump(
        data,

        sort_keys=False,

        allow_unicode=True,

        width=1000,
    )


    path.write_text(
        header
        +
        rendered,

        encoding="utf-8",
    )


# ============================================================
# Control metadata
# ============================================================

def source_profile(
    control: dict[str, Any],
) -> str:

    tags = set(
        control.get(
            "tags",
            [],
        )
    )


    if (
        "source-profile:level1"
        in
        tags
    ):

        return "level1"


    if (
        "source-profile:level2"
        in
        tags
    ):

        return "level2"


    if (
        "source-profile:bitlocker"
        in
        tags
    ):

        return "bitlocker"


    if (
        "source-profile:next-generation"
        in
        tags
    ):

        return "next-generation"


    raise RuntimeError(
        "Control does not contain a recognized "
        "source-profile tag."
    )


def is_addon_control(
    control: dict[str, Any],
) -> bool:

    return source_profile(
        control
    ) in {
        "bitlocker",
        "next-generation",
    }


def classification_counts(
    controls: dict[
        str,
        dict[str, Any]
    ],
) -> Counter[str]:

    return Counter(

        str(
            control.get(
                "crucible_implementation"
            )
        )

        for control
        in controls.values()
    )


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


# ============================================================
# PDF extraction
# ============================================================

def extract_pdf_text(
    pdf_path: Path,
) -> str:

    pdftotext = shutil.which(
        "pdftotext"
    )


    if (
        pdftotext
        is None
    ):

        raise RuntimeError(
            "pdftotext was not found. "
            "Install poppler-utils on the controller."
        )


    with tempfile.TemporaryDirectory(
        prefix="crucible-win10-bc-g-"
    ) as temporary_directory:

        text_path = (
            Path(
                temporary_directory
            )
            /
            "benchmark.txt"
        )


        result = subprocess.run(

            [
                pdftotext,

                "-layout",

                str(
                    pdf_path
                ),

                str(
                    text_path
                ),
            ],

            text=True,

            capture_output=True,

            check=False,
        )


        if (
            result.returncode
            !=
            0
        ):

            raise RuntimeError(
                "pdftotext failed:\n"
                +
                result.stderr
            )


        return text_path.read_text(
            encoding="utf-8",

            errors="replace",
        )


def extract_recommendation_blocks(
    text: str,
    wanted_ids: set[str],
) -> dict[
    str,
    str
]:

    matches = list(
        RECOMMENDATION_START.finditer(
            text
        )
    )


    blocks: dict[
        str,
        str
    ] = {}


    for (
        index,
        match,
    ) in enumerate(
        matches
    ):

        control_id = (
            match.group(
                "control"
            )
        )


        if (
            control_id
            not in
            wanted_ids
        ):

            continue


        if (
            index
            +
            1
            <
            len(
                matches
            )
        ):

            end = (
                matches[
                    index
                    +
                    1
                ].start()
            )


        else:

            end = len(
                text
            )


        block = text[
            match.start()
            :
            end
        ]


        # ----------------------------------------------------
        # Reject TOC and Summary Table occurrences.
        # ----------------------------------------------------

        if (
            "Profile Applicability:"
            not in
            block
        ):

            continue


        if (
            "Audit:"
            not in
            block
        ):

            continue


        blocks[
            control_id
        ] = block


    missing = sorted(
        wanted_ids
        -
        set(
            blocks
        )
    )


    if missing:

        raise RuntimeError(
            "Could not find full recommendation blocks "
            "for:\n"
            +
            "\n".join(
                missing
            )
        )


    return blocks


# ============================================================
# Registry extraction
# ============================================================

def audit_section(
    block: str,
) -> str:

    match = re.search(

        r"Audit:\s*"
        r"(?P<audit>.*?)"
        r"\s*Remediation:",

        block,

        flags=re.DOTALL,
    )


    if (
        match
        is None
    ):

        raise ValueError(
            "Recommendation has no parseable "
            "Audit -> Remediation section."
        )


    return match.group(
        "audit"
    )


def is_stop_line(
    line: str,
) -> bool:

    stripped = line.strip()


    if (
        not stripped
    ):

        return False


    return any(

        stripped.startswith(
            prefix
        )

        for prefix
        in STOP_LINE_PREFIXES
    )


def extract_registry_locations(
    audit: str,
) -> list[
    tuple[
        int,
        str,
    ]
]:

    lines = audit.splitlines()

    locations: list[
        tuple[
            int,
            str,
        ]
    ] = []


    index = 0


    while (
        index
        <
        len(
            lines
        )
    ):

        current = (
            lines[
                index
            ]
            .strip()
            .replace(
                "\u00ad",
                "",
            )
        )


        if (
            REGISTRY_ROOT.match(
                current
            )
            is None
        ):

            index += 1

            continue


        start_index = index

        pieces = [
            current
        ]


        cursor = (
            index
            +
            1
        )


        while (
            cursor
            <
            len(
                lines
            )
        ):

            next_line = (
                lines[
                    cursor
                ]
                .strip()
                .replace(
                    "\u00ad",
                    "",
                )
            )


            if (
                not next_line
            ):

                cursor += 1

                continue


            if (
                REGISTRY_ROOT.match(
                    next_line
                )
                is not None
            ):

                break


            if is_stop_line(
                next_line
            ):

                break


            combined = "".join(
                pieces
            )


            # ------------------------------------------------
            # Registry key itself wrapped before ":ValueName".
            #
            # Join without an inserted space because PDF line
            # wrapping can split a registry path in the middle
            # of a token.
            # ------------------------------------------------

            if (
                ":"
                not in
                combined
            ):

                pieces.append(
                    next_line
                )

                cursor += 1

                continue


            # ------------------------------------------------------------
            # The registry value name itself can wrap across PDF lines:
            #
            #     :SaveZoneI
            #     nformation
            #
            # pdftotext may additionally attach a page marker:
            #
            #     nformationPage 1228
            #
            # Preserve only the registry-token portion.
            # ------------------------------------------------------------

            continuation_match = (
                re.fullmatch(
                    (
                        r"(?P<token>"
                        r"[A-Za-z0-9_.{}-]+?"
                        r")"
                        r"(?:Page\s+\d+)?"
                    ),
                    next_line,
                )
            )


            if (
                continuation_match
                is not None
            ):

                pieces.append(
                    continuation_match.group(
                        "token"
                    )
                )

                cursor += 1


            break


        location = "".join(
            pieces
        )


        locations.append(
            (
                start_index,
                location,
            )
        )


        index = max(
            cursor,
            index
            +
            1,
        )


    return locations


def descriptor_for_location(
    audit_lines: list[str],
    location_index: int,
) -> tuple[
    str,
    str,
]:

    start = max(
        0,
        location_index
        -
        12,
    )


    window = " ".join(

        line.strip()

        for line
        in audit_lines[
            start
            :
            location_index
        ]
    )


    window = re.sub(
        r"\s+",
        " ",
        window,
    )


    matches = list(
        REGISTRY_DESCRIPTOR.finditer(
            window
        )
    )


    if (
        not matches
    ):

        raise ValueError(
            "Could not find registry type/value "
            "descriptor immediately before "
            "registry location."
        )


    match = matches[
        -1
    ]


    type1 = (
        match.group(
            "type1"
        )
        .upper()
    )


    type2 = (
        match.group(
            "type2"
        )
    )


    available_types = [
        type1
    ]


    if type2:

        available_types.append(
            type2.upper()
        )


    # --------------------------------------------------------
    # Some CIS recommendations explicitly permit:
    #
    #     REG_DWORD or REG_SZ value of 1
    #
    # Prefer DWORD where available because that is the normal
    # Group Policy representation and avoids ambiguous string
    # coercion.
    # --------------------------------------------------------

    priority = [

        "DWORD",

        "QWORD",

        "SZ",

        "EXPAND_SZ",

        "MULTI_SZ",
    ]


    chosen_type = next(

        candidate

        for candidate
        in priority

        if candidate
        in
        available_types
    )


    value_text = (
        match.group(
            "value"
        )
        .strip()
    )


    return (
        chosen_type,
        value_text,
    )


def parse_numeric(
    value_text: str,
) -> int:

    hexadecimal = re.search(
        r"0x[0-9a-fA-F]+",
        value_text,
    )


    if hexadecimal:

        return int(
            hexadecimal.group(
                0
            ),
            16,
        )


    decimal = re.search(
        r"-?\d[\d,]*",
        value_text,
    )


    if (
        decimal
        is None
    ):

        raise ValueError(
            "No numeric value found in "
            f"'{value_text}'."
        )


    return int(
        decimal.group(
            0
        ).replace(
            ",",
            "",
        )
    )


def parse_string(
    value_text: str,
) -> str:

    if re.search(
        r"\bblank\b",
        value_text,
        re.IGNORECASE,
    ):

        return ""


    quoted = re.search(
        r"""['"]([^'"]*)['"]""",
        value_text,
    )


    if quoted:

        return quoted.group(
            1
        )


    first_choice = re.split(
        r"\s+or\s+",
        value_text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[
        0
    ]


    return (
        first_choice
        .strip()
        .rstrip(
            "."
        )
    )


def parse_multistring(
    value_text: str,
) -> list[str]:

    normalized = re.sub(
        r"\s+and\s+",
        ", ",
        value_text,
        flags=re.IGNORECASE,
    )


    values = [

        item.strip()

        for item
        in normalized.split(
            ","
        )

        if item.strip()
    ]


    if (
        not values
    ):

        raise ValueError(
            "Could not parse MULTI_SZ data "
            f"from '{value_text}'."
        )


    return values


def parse_registry_data(
    registry_type: str,
    value_text: str,
) -> Any:

    if (
        registry_type
        ==
        "DWORD"
    ):

        return parse_numeric(
            value_text
        )


    if (
        registry_type
        ==
        "QWORD"
    ):

        return parse_numeric(
            value_text
        )


    if registry_type in {
        "SZ",
        "EXPAND_SZ",
    }:

        return parse_string(
            value_text
        )


    if (
        registry_type
        ==
        "MULTI_SZ"
    ):

        return parse_multistring(
            value_text
        )


    raise ValueError(
        f"Unsupported registry type: "
        f"{registry_type}"
    )


def ansible_registry_type(
    registry_type: str,
) -> str:

    mapping = {

        "DWORD":
            "dword",

        "QWORD":
            "qword",

        "SZ":
            "string",

        "EXPAND_SZ":
            "expandstring",

        "MULTI_SZ":
            "multistring",
    }


    return mapping[
        registry_type
    ]


def parse_location(
    location: str,
) -> tuple[
    str,
    str,
    str,
]:

    cleaned = (
        location
        .replace(
            "\u00ad",
            "",
        )
        .strip()
    )


    if (
        "\\"
        not in
        cleaned
    ):

        raise ValueError(
            "Registry location has no hive/path "
            f"separator: {cleaned}"
        )


    raw_hive, rest = (
        cleaned.split(
            "\\",
            1,
        )
    )


    normalized_hive = (
        raw_hive
        .strip()
        .upper()
    )


    try:

        hive = (
            REGISTRY_HIVE_ALIASES[
                normalized_hive
            ]
        )


    except KeyError as exc:

        raise ValueError(
            "Unsupported registry hive: "
            f"{raw_hive}"
        ) from exc


    # ========================================================
    # CIS user-policy notation
    #
    # The Windows 10 benchmark represents generic per-user
    # policies as:
    #
    #     HKU\[USER SID]\Software\...
    #
    # pdftotext may wrap this as:
    #
    #     HKU\[USER
    #     SID]\Software\...
    #
    # and our line joiner therefore may produce:
    #
    #     HKU\[USERSID]\Software\...
    #
    # Both forms mean the same thing:
    #
    #     apply to each real user hive.
    #
    # Normalize that semantic target to HKCU while removing
    # the placeholder component. The generated inventory then
    # enters Crucible's all-user registry engine rather than
    # being written only to the WinRM administrator's HKCU.
    # ========================================================

    if (
        hive
        ==
        "HKU"
    ):

        if (
            "\\"
            not in
            rest
        ):

            raise ValueError(
                "HKU registry location has no "
                "user-SID/path component: "
                f"{cleaned}"
            )


        user_component, user_rest = (
            rest.split(
                "\\",
                1,
            )
        )


        normalized_user_component = (
            re.sub(
                r"[^A-Za-z0-9]",
                "",
                user_component,
            )
            .upper()
        )


        if (
            normalized_user_component
            !=
            "USERSID"
        ):

            raise ValueError(
                "HKU location references a specific "
                "or unsupported user hive rather than "
                "the CIS [USER SID] placeholder: "
                f"{cleaned}"
            )


        hive = "HKCU"

        rest = user_rest


    if (
        ":"
        not in
        rest
    ):

        raise ValueError(
            "Registry location has no "
            "':ValueName' delimiter: "
            f"{cleaned}"
        )


    key_path, value_name = (
        rest.rsplit(
            ":",
            1,
        )
    )


    key_path = (
        key_path.strip()
    )

    value_name = (
        value_name.strip()
    )


    if (
        not key_path
    ):

        raise ValueError(
            "Registry location has an empty key path: "
            f"{cleaned}"
        )


    if (
        not value_name
    ):

        raise ValueError(
            "Registry location has an empty value name: "
            f"{cleaned}"
        )


    return (
        hive,
        key_path,
        value_name,
    )


def registry_entries_for_control(
    control_id: str,
    block: str,
) -> list[
    dict[str, Any]
]:

    audit = audit_section(
        block
    )


    lines = audit.splitlines()


    locations = (
        extract_registry_locations(
            audit
        )
    )


    if (
        not locations
    ):

        raise ValueError(
            "No supported Windows registry location "
            "was found in the Audit section."
        )


    results: list[
        dict[str, Any]
    ] = []


    seen: set[
        tuple[
            str,
            str,
            str,
        ]
    ] = set()


    for (
        line_index,
        raw_location,
    ) in locations:

        registry_type, value_text = (
            descriptor_for_location(
                lines,
                line_index,
            )
        )


        data = parse_registry_data(
            registry_type,
            value_text,
        )


        hive, key_path, value_name = (
            parse_location(
                raw_location
            )
        )


        identity = (
            hive,
            key_path.lower(),
            value_name.lower(),
        )


        if (
            identity
            in
            seen
        ):

            continue


        seen.add(
            identity
        )


        result: dict[
            str,
            Any
        ] = {

            "control_id":
                control_id,

            "name":
                value_name,

            "type":
                ansible_registry_type(
                    registry_type
                ),

            "data":
                data,

            # Development traceability. The runtime tasks
            # ignore this field.
            "source_value_text":
                value_text,
        }


        if (
            hive
            ==
            "HKLM"
        ):

            result[
                "path"
            ] = (
                "HKLM:\\"
                +
                key_path
            )


        else:

            result[
                "subkey"
            ] = (
                key_path
            )


        results.append(
            result
        )


    return results


# ============================================================
# Policy generation
# ============================================================

def generate_registry_inventory(
    pdf_text: str,
    target_ids: set[str],
) -> tuple[
    list[
        dict[str, Any]
    ],
    list[
        dict[str, Any]
    ],
    dict[
        str,
        str
    ],
]:

    blocks = (
        extract_recommendation_blocks(
            pdf_text,
            target_ids,
        )
    )


    machine: list[
        dict[str, Any]
    ] = []


    user: list[
        dict[str, Any]
    ] = []


    unresolved: dict[
        str,
        str
    ] = {}


    for control_id in sorted(
        target_ids
    ):

        # ----------------------------------------------------
        # Explicit overrides are intentionally checked before
        # generic PDF parsing.
        #
        # This lets Crucible handle a very small number of
        # benchmark recommendations whose Audit text is not
        # sufficiently machine-readable without weakening the
        # fail-closed behavior of the generic parser.
        # ----------------------------------------------------

        if (
            control_id
            in
            REGISTRY_POLICY_OVERRIDES
        ):

            entries = [

                dict(
                    entry
                )

                for entry
                in
                REGISTRY_POLICY_OVERRIDES[
                    control_id
                ]
            ]


        else:

            try:

                entries = (
                    registry_entries_for_control(
                        control_id,
                        blocks[
                            control_id
                        ],
                    )
                )


            except (
                ValueError,
                KeyError,
            ) as exc:

                unresolved[
                    control_id
                ] = str(
                    exc
                )

                continue


        for entry in entries:

            if (
                "path"
                in
                entry
            ):

                machine.append(
                    entry
                )


            else:

                user.append(
                    entry
                )


    return (
        machine,
        user,
        unresolved,
    )


# ============================================================
# Benchmark promotion
# ============================================================

def remove_engineering_tags(
    tags: list[str],
) -> list[str]:

    remove = {

        "risk:unreviewed",

        "risk:high",

        "risk:medium",

        "risk:low",

        "wave:deferred",

        "wave:1",

        "wave:2",

        "wave:3",

        "implementation-pending",
    }


    return [

        tag

        for tag
        in tags

        if tag
        not in
        remove
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


def control_area(
    control_id: str,
) -> str:

    if control_id.startswith(
        "5."
    ):

        return (
            "system-services"
        )


    if control_id.startswith(
        "2.3."
    ):

        return (
            "security-options"
        )


    if control_id.startswith(
        "18."
    ):

        return (
            "administrative-templates-computer"
        )


    if control_id.startswith(
        "19."
    ):

        return (
            "administrative-templates-user"
        )


    raise RuntimeError(
        "BC-G encountered unexpected control "
        f"area for {control_id}."
    )


def promote_bc_g_control(
    control_id: str,
    control: dict[str, Any],
) -> None:

    source = source_profile(
        control
    )


    if source not in {
        "level1",
        "level2",
    }:

        raise RuntimeError(
            "BC-G attempted to promote add-on "
            f"control {control_id}."
        )


    tags = (
        remove_engineering_tags(
            list(
                control.get(
                    "tags",
                    [],
                )
            )
        )
    )


    area = control_area(
        control_id
    )


    # Preserve a more specific existing area if a previous
    # milestone already reviewed the control.
    if not any(
        tag.startswith(
            "area:"
        )
        for tag
        in tags
    ):

        tags = add_unique(
            tags,
            f"area:{area}",
        )


    if (
        source
        ==
        "level1"
    ):

        tags = add_unique(
            tags,

            "risk:medium",

            "wave:1",
        )


    else:

        tags = add_unique(
            tags,

            "risk:high",

            "wave:2",

            "level2-impact",
        )


    if control_id.startswith(
        "5."
    ):

        tags = add_unique(
            tags,

            "backend:powershell",

            "service-aware",
        )


    else:

        tags = add_unique(
            tags,

            "backend:registry",

            "generated-from:cis-audit-registry-backing",
        )


        if control_id.startswith(
            "19."
        ):

            tags = add_unique(
                tags,

                "registry-scope:user",
            )


        else:

            tags = add_unique(
                tags,

                "registry-scope:machine",
            )


    tags = add_unique(
        tags,
        "reviewed:bc-g",
    )


    if (
        control_id
        in
        MANAGEMENT_SENSITIVE_CONTROLS
    ):

        tags = add_unique(
            tags,

            "management-sensitive",

            (
                "preserve-if-capability:"
                "management:winrm"
            ),
        )


        control[
            "crucible_implementation"
        ] = "conditional"


    else:

        control[
            "crucible_implementation"
        ] = "automated"


    control[
        "tags"
    ] = tags


# ============================================================
# Main
# ============================================================

def main() -> int:

    parser = argparse.ArgumentParser(

        description=(
            "Implement Operation Crucible Windows 10 "
            "CIS milestone BC-G."
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
            f"Benchmark PDF not found: "
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


    pre_counts = (
        classification_counts(
            controls
        )
    )


    validate_counts(
        pre_counts,
        EXPECTED_PRE_BC_G,
        stage="BC-F starting state",
    )


    # --------------------------------------------------------
    # Find all remaining standard L1/L2 controls.
    #
    # BL and NG remain untouched for BC-H.
    # --------------------------------------------------------

    target_ids = {

        str(
            control_id
        )

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

        and

        not is_addon_control(
            control
        )
    }


    if (
        len(
            target_ids
        )
        !=
        EXPECTED_BC_G_TOTAL
    ):

        raise RuntimeError(
            "Expected "
            f"{EXPECTED_BC_G_TOTAL} "
            "remaining standard controls, found "
            f"{len(target_ids)}."
        )


    service_ids = {

        control_id

        for control_id
        in target_ids

        if control_id.startswith(
            "5."
        )
    }


    registry_ids = (
        target_ids
        -
        service_ids
    )


    if (
        len(
            service_ids
        )
        !=
        EXPECTED_BC_G_SERVICES
    ):

        raise RuntimeError(
            "Expected "
            f"{EXPECTED_BC_G_SERVICES} "
            "BC-G service controls, found "
            f"{len(service_ids)}."
        )


    if (
        len(
            registry_ids
        )
        !=
        EXPECTED_BC_G_REGISTRY_CONTROLS
    ):

        raise RuntimeError(
            "Expected "
            f"{EXPECTED_BC_G_REGISTRY_CONTROLS} "
            "BC-G registry controls, found "
            f"{len(registry_ids)}."
        )


    # --------------------------------------------------------
    # Parse the PDF before modifying benchmark classifications.
    #
    # If even one policy cannot be resolved, nothing is
    # promoted.
    # --------------------------------------------------------

    print(
        "Extracting CIS benchmark text..."
    )


    pdf_text = extract_pdf_text(
        pdf_path
    )


    print(
        "Resolving BC-G registry-backed policies..."
    )


    (
        machine_policies,
        user_policies,
        unresolved,
    ) = generate_registry_inventory(
        pdf_text,
        registry_ids,
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
        registry_ids
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
                "BC-G",

            "expected_registry_controls":
                EXPECTED_BC_G_REGISTRY_CONTROLS,

            "resolved_control_count":
                len(
                    resolved_ids
                ),

            "unresolved": {

                control_id: (
                    unresolved.get(
                        control_id,
                        "No generated registry entry."
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
            "BC-G registry extraction was incomplete. "
            "No benchmark classifications were changed.\n"
            f"Review: {UNRESOLVED_PATH}"
        )


    if (
        len(
            resolved_ids
        )
        !=
        EXPECTED_BC_G_REGISTRY_CONTROLS
    ):

        raise RuntimeError(
            "BC-G resolved an unexpected number "
            "of registry controls."
        )


    # --------------------------------------------------------
    # Write generated registry-policy data.
    # --------------------------------------------------------

    policy_header = """# Operation Crucible
#
# Generated BC-G Windows 10 CIS registry policy inventory.
#
# SOURCE:
#   CIS Microsoft Windows 10 Stand-alone Benchmark v4.0.0
#
# This file was generated from the registry backing stated in
# each recommendation's Audit procedure.
#
# Do not hand-edit this file. Re-run:
#
#   tools/implement_windows10_cis_bc_g.py <benchmark.pdf>
#
# if the source inventory must be regenerated.
#
"""


    policy_data = {

        "crucible_cis_windows_10_bc_g_machine_registry_policies":
            machine_policies,

        "crucible_cis_windows_10_bc_g_user_registry_policies":
            user_policies,
    }


    write_yaml(
        OUTPUT_POLICY_PATH,
        policy_data,
        header=(
            policy_header
        ),
    )


    # --------------------------------------------------------
    # Promote the successfully generated controls.
    # --------------------------------------------------------

    for control_id in sorted(
        target_ids
    ):

        promote_bc_g_control(
            control_id,
            controls[
                control_id
            ],
        )


    post_counts = (
        classification_counts(
            controls
        )
    )


    validate_counts(
        post_counts,
        EXPECTED_POST_BC_G,
        stage="BC-G final state",
    )


    remaining = {

        control_id: control

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
        EXPECTED_REMAINING_ADDONS
    ):

        raise RuntimeError(
            "BC-G should leave exactly "
            f"{EXPECTED_REMAINING_ADDONS} "
            "BL/NG controls pending."
        )


    for (
        control_id,
        control,
    ) in remaining.items():

        if not is_addon_control(
            control
        ):

            raise RuntimeError(
                "BC-G left a standard L1/L2 control "
                f"unimplemented: {control_id}"
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
        "BC-G complete."
    )

    print(
        f"  Standard controls promoted: "
        f"{len(target_ids)}"
    )

    print(
        f"  Level 2 services: "
        f"{len(service_ids)}"
    )

    print(
        f"  Registry controls: "
        f"{len(registry_ids)}"
    )

    print(
        f"  Machine registry entries: "
        f"{len(machine_policies)}"
    )

    print(
        f"  User registry entries: "
        f"{len(user_policies)}"
    )

    print()
    print(
        "Remaining not implemented: "
        f"{len(remaining)} "
        "(BitLocker / Next Generation only)"
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