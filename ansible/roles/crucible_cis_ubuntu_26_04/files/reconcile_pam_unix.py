#!/usr/bin/env python3

from pathlib import Path
import sys


PATH = Path(
    "/usr/share/pam-configs/unix"
)

KNOWN_SECTIONS = {
    "Auth",
    "Auth-Initial",
    "Account",
    "Account-Initial",
    "Session",
    "Session-Initial",
    "Password",
    "Password-Initial",
}


def fail(
    message: str,
) -> None:

    print(
        message,
        file=sys.stderr,
    )

    raise SystemExit(
        1
    )


if not PATH.is_file():
    fail(
        f"Missing PAM Unix profile: {PATH}"
    )


original = PATH.read_text(
    encoding="utf-8",
)

lines = original.splitlines()

section: str | None = None

seen_password = False
seen_password_initial = False
seen_unix = False

output: list[str] = []


for raw_line in lines:

    stripped = raw_line.strip()

    if (
        stripped.endswith(":")
        and
        stripped[:-1]
        in KNOWN_SECTIONS
    ):

        section = stripped[:-1]

        output.append(
            raw_line
        )

        continue


    if "pam_unix.so" not in raw_line:

        output.append(
            raw_line
        )

        continue


    seen_unix = True

    indent = (
        raw_line[
            :len(raw_line)
            -
            len(raw_line.lstrip())
        ]
    )

    tokens = (
        raw_line.strip().split()
    )

    try:

        module_index = (
            tokens.index(
                "pam_unix.so"
            )
        )

    except ValueError:

        output.append(
            raw_line
        )

        continue


    prefix = tokens[
        :module_index + 1
    ]

    options = tokens[
        module_index + 1:
    ]


    options = [

        option

        for option
        in options

        if (
            option
            not in {
                "nullok",
                "nullok_secure",
            }

            and

            not option.startswith(
                "remember="
            )
        )
    ]


    if section == "Password":

        seen_password = True

        #
        # Password changes must consume the token
        # produced by the preceding password-quality /
        # history modules.
        #

        if (
            "use_authtok"
            not in options
        ):
            options.append(
                "use_authtok"
            )

        if (
            "try_first_pass"
            not in options
        ):
            options.append(
                "try_first_pass"
            )

        #
        # Remove alternate explicit hashing algorithms
        # before selecting yescrypt.
        #

        hash_options = {
            "md5",
            "bigcrypt",
            "sha256",
            "sha512",
            "blowfish",
            "gost_yescrypt",
            "des",
        }

        options = [

            option

            for option
            in options

            if option
            not in hash_options
        ]

        if (
            "yescrypt"
            not in options
        ):
            options.append(
                "yescrypt"
            )


    elif section == "Password-Initial":

        seen_password_initial = True

        #
        # CIS explicitly distinguishes Password-Initial:
        # use_authtok must not be forced here.
        #

        options = [

            option

            for option
            in options

            if option
            != "use_authtok"
        ]

        hash_options = {
            "md5",
            "bigcrypt",
            "sha256",
            "sha512",
            "blowfish",
            "gost_yescrypt",
            "des",
        }

        options = [

            option

            for option
            in options

            if option
            not in hash_options
        ]

        if (
            "yescrypt"
            not in options
        ):
            options.append(
                "yescrypt"
            )


    resolved = (
        indent
        +
        " ".join(
            prefix
            +
            options
        )
    )

    output.append(
        resolved
    )


if not seen_unix:
    fail(
        "The PAM Unix profile does not contain "
        "pam_unix.so."
    )


if not seen_password:
    fail(
        "The PAM Unix profile does not contain "
        "a Password pam_unix.so entry."
    )


if not seen_password_initial:
    fail(
        "The PAM Unix profile does not contain "
        "a Password-Initial pam_unix.so entry."
    )


resolved_text = (
    "\n".join(
        output
    )
    +
    "\n"
)


if resolved_text != original:

    PATH.write_text(
        resolved_text,
        encoding="utf-8",
    )


raise SystemExit(
    0
)