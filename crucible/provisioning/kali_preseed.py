from __future__ import annotations

import base64
import ipaddress
import re
import uuid
from pathlib import Path
from typing import Any


class KaliPreseedError(RuntimeError):
    """Expected Kali preseed generation error."""


USERNAME_PATTERN = re.compile(
    r"^[a-z_][a-z0-9_-]*[$]?$"
)


def _load_jinja_environment(
    template_dir: Path,
):
    try:
        from jinja2 import (
            Environment,
            FileSystemLoader,
            StrictUndefined,
        )

    except ModuleNotFoundError as exc:
        raise KaliPreseedError(
            "Jinja2 is required for Kali "
            "preseed generation."
        ) from exc

    return Environment(
        loader=FileSystemLoader(
            str(template_dir)
        ),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )


def _country_from_locale(
    locale: str,
) -> str:
    try:
        country = (
            locale
            .split("_", 1)[1]
            .split(".", 1)[0]
            .upper()
        )

        if len(country) == 2:
            return country

    except IndexError:
        pass

    return "CA"


def _validate_rendered_preseed(
    path: Path,
) -> None:
    text = path.read_text(
        encoding="utf-8"
    )

    required = (
        "d-i netcfg/choose_interface",
        "d-i passwd/username",
        "d-i passwd/user-password-crypted",
        "d-i partman-auto/method",
        "d-i preseed/late_command",
        "d-i finish-install/reboot_in_progress",
    )

    for item in required:
        if item not in text:
            raise KaliPreseedError(
                "Rendered Kali preseed is "
                f"missing required setting: "
                f"{item}"
            )

    if "{{" in text or "{%" in text:
        raise KaliPreseedError(
            "Rendered Kali preseed still "
            "contains Jinja template syntax."
        )


def build_preseed(
    machine_manifest: dict[str, Any],
    *,
    repo_root: Path,
    verbose: bool = False,
) -> Path:
    machine_name = str(
        machine_manifest.get(
            "name",
            "",
        )
    ).strip()

    if not machine_name:
        raise KaliPreseedError(
            "Machine manifest has no name."
        )

    unattended = machine_manifest.get(
        "autoinstall"
    )

    if not isinstance(
        unattended,
        dict,
    ):
        raise KaliPreseedError(
            "Machine manifest has no "
            "autoinstall mapping."
        )

    if not unattended.get(
        "enabled",
        False,
    ):
        raise KaliPreseedError(
            "Kali preseed generation was "
            "requested but unattended "
            "installation is disabled."
        )

    identity = unattended.get(
        "identity",
        {},
    )

    keyboard = unattended.get(
        "keyboard",
        {},
    )

    ssh = unattended.get(
        "ssh",
        {},
    )

    username = str(
        identity.get(
            "username",
            "",
        )
    ).strip()

    if not USERNAME_PATTERN.fullmatch(
        username
    ):
        raise KaliPreseedError(
            f"Invalid Linux username: "
            f"{username!r}"
        )

    password_hash = str(
        identity.get(
            "password_hash",
            "",
        )
    ).strip()

    if not password_hash:
        raise KaliPreseedError(
            "Kali installation requires "
            "identity.password_hash."
        )

    network = machine_manifest.get(
        "network",
        {},
    )

    management = network.get(
        "management",
        {},
    )

    management_address = str(
        management.get(
            "address",
            "",
        )
    ).strip()

    if not management_address:
        raise KaliPreseedError(
            "Machine manifest is missing "
            "network.management.address."
        )

    try:
        management_interface = (
            ipaddress.ip_interface(
                management_address
            )
        )

    except ValueError as exc:
        raise KaliPreseedError(
            "Invalid management address: "
            f"{management_address}"
        ) from exc

    if not isinstance(
        management_interface,
        ipaddress.IPv4Interface,
    ):
        raise KaliPreseedError(
            "Kali management networking "
            "currently requires IPv4."
        )

    template_dir = (
        repo_root
        / "installers"
        / "linux"
        / "kali"
        / "templates"
    )

    template_path = (
        template_dir
        / "preseed.cfg.j2"
    )

    if not template_path.is_file():
        raise KaliPreseedError(
            "Kali preseed template "
            f"not found: {template_path}"
        )

    bootstrap_path = (
        repo_root
        / "installers"
        / "linux"
        / "common"
        / "bootstrap.sh"
    )

    if not bootstrap_path.is_file():
        raise KaliPreseedError(
            "Linux bootstrap script "
            f"not found: {bootstrap_path}"
        )

    bootstrap_base64 = (
        base64.b64encode(
            bootstrap_path.read_bytes()
        )
        .decode("ascii")
    )

    bootstrap_service = (
        "[Unit]\n"
        "Description=Operation Crucible First-Boot Bootstrap\n"
        "Wants=network-online.target\n"
        "After=network-online.target\n"
        "ConditionPathExists=!/var/lib/crucible/bootstrap-complete\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=/usr/local/sbin/crucible-bootstrap.sh\n"
        "RemainAfterExit=yes\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )

    bootstrap_service_base64 = (
        base64.b64encode(
            bootstrap_service.encode(
                "utf-8"
            )
        )
        .decode("ascii")
    )
    
    nat_connection_uuid = str(
        uuid.uuid4()
    )

    management_connection_uuid = str(
        uuid.uuid4()
    )

    nat_connection = (
        "[connection]\n"
        "id=crucible-nat\n"
        f"uuid={nat_connection_uuid}\n"
        "type=ethernet\n"
        "interface-name=eth0\n"
        "autoconnect=true\n"
        "\n"
        "[ethernet]\n"
        "\n"
        "[ipv4]\n"
        "method=auto\n"
        "\n"
        "[ipv6]\n"
        "method=disabled\n"
    )

    management_connection = (
        "[connection]\n"
        "id=crucible-management\n"
        f"uuid={management_connection_uuid}\n"
        "type=ethernet\n"
        "interface-name=eth1\n"
        "autoconnect=true\n"
        "\n"
        "[ethernet]\n"
        "\n"
        "[ipv4]\n"
        "method=manual\n"
        f"address1={management_interface.ip}/"
        f"{management_interface.network.prefixlen}\n"
        "never-default=true\n"
        "\n"
        "[ipv6]\n"
        "method=disabled\n"
    )

    nat_connection_base64 = (
        base64.b64encode(
            nat_connection.encode(
                "utf-8"
            )
        )
        .decode("ascii")
    )


    management_connection_base64 = (
        base64.b64encode(
            management_connection.encode(
                "utf-8"
            )
        )
        .decode("ascii")
    )

    late_commands = [
        (
            "in-target install "
            "-d -m 0755 "
            "/etc/NetworkManager/"
            "system-connections"
        ),

        (
            "in-target /bin/sh -c "
            "\"printf '%s' "
            f"'{nat_connection_base64}' "
            "| base64 -d "
            "> /etc/NetworkManager/"
            "system-connections/"
            "crucible-nat.nmconnection\""
        ),

        (
            "in-target chmod 0600 "
            "/etc/NetworkManager/"
            "system-connections/"
            "crucible-nat.nmconnection"
        ),

        (
            "in-target /bin/sh -c "
            "\"printf '%s' "
            f"'{management_connection_base64}' "
            "| base64 -d "
            "> /etc/NetworkManager/"
            "system-connections/"
            "crucible-management.nmconnection\""
        ),

        (
            "in-target chmod 0600 "
            "/etc/NetworkManager/"
            "system-connections/"
            "crucible-management.nmconnection"
        ),

        (
            "in-target systemctl enable "
            "NetworkManager"
        ),

        (
            "in-target /bin/sh -c "
            "\"printf '%s' "
            f"'{bootstrap_base64}' "
            "| base64 -d "
            "> /usr/local/sbin/"
            "crucible-bootstrap.sh\""
        ),

        (
            "in-target chmod 0755 "
            "/usr/local/sbin/"
            "crucible-bootstrap.sh"
        ),
    ]

    authorized_keys = list(
        ssh.get(
            "authorized_keys",
            [],
        )
    )

    if authorized_keys:
        keys_text = (
            "\n".join(
                str(key).strip()
                for key in authorized_keys
                if str(key).strip()
            )
            + "\n"
        )

        keys_base64 = (
            base64.b64encode(
                keys_text.encode(
                    "utf-8"
                )
            )
            .decode("ascii")
        )

        late_commands.extend(
            [
                (
                    "in-target install "
                    "-d -m 0700 "
                    f"-o {username} "
                    f"-g {username} "
                    f"/home/{username}/.ssh"
                ),
                (
                    "in-target /bin/sh -c "
                    "\"printf '%s' "
                    f"'{keys_base64}' "
                    "| base64 -d "
                    f"> /home/{username}/"
                    "ssh-authorized-keys.tmp\""
                ),
                (
                    "in-target mv "
                    f"/home/{username}/"
                    "ssh-authorized-keys.tmp "
                    f"/home/{username}/"
                    ".ssh/authorized_keys"
                ),
                (
                    "in-target chown "
                    f"{username}:{username} "
                    f"/home/{username}/"
                    ".ssh/authorized_keys"
                ),
                (
                    "in-target chmod 0600 "
                    f"/home/{username}/"
                    ".ssh/authorized_keys"
                ),
            ]
        )

    late_commands.extend(
        [
            (
                "in-target ssh-keygen -A"
            ),

            (
                "in-target systemctl enable "
                "ssh.service"
            ),

            (
                "in-target /bin/sh -c "
                "\"printf '%s' "
                f"'{bootstrap_service_base64}' "
                "| base64 -d "
                "> /etc/systemd/system/"
                "crucible-bootstrap.service\""
            ),

            (
                "in-target chmod 0644 "
                "/etc/systemd/system/"
                "crucible-bootstrap.service"
            ),

            (
                "in-target systemctl enable "
                "crucible-bootstrap.service"
            ),

            (
                "in-target mkdir -p "
                "/var/lib/crucible"
            ),

            (
                "in-target touch "
                "/var/lib/crucible/"
                "preseed-late-command-complete"
            ),
        ]
    )

    locale = str(
        unattended.get(
            "locale",
            "en_CA.UTF-8",
        )
    )

    context = {
        "hostname": unattended.get(
            "hostname",
            machine_name,
        ),

        "realname": identity.get(
            "realname",
            "Crucible User",
        ),

        "username": username,

        "password_hash": (
            password_hash
        ),

        "locale": locale,

        "country": (
            _country_from_locale(
                locale
            )
        ),

        "timezone": unattended.get(
            "timezone",
            "America/Toronto",
        ),

        "keyboard_layout": (
            keyboard.get(
                "layout",
                "us",
            )
        ),

        "late_command": (
            "; ".join(
                late_commands
            )
        ),
    }

    build_dir = (
        repo_root
        / ".crucible"
        / "generated"
        / "preseed"
        / machine_name
    )

    build_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        build_dir
        / "preseed.cfg"
    )

    environment = (
        _load_jinja_environment(
            template_dir
        )
    )

    template = (
        environment.get_template(
            "preseed.cfg.j2"
        )
    )

    output_path.write_text(
        template.render(
            **context
        ),
        encoding="utf-8",
    )

    _validate_rendered_preseed(
        output_path
    )

    if verbose:
        print(
            f"Rendered Kali preseed: "
            f"{output_path}"
        )

    return output_path
