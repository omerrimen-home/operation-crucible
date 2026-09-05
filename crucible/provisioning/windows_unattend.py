from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
import ipaddress
import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from crucible.networking.topology import (
    CRUCIBLE_NAT_ROUTE_METRIC,
    TOPOLOGY_ROUTE_METRIC,
)

class WindowsUnattendError(RuntimeError):
    """
    Expected Windows unattended-install generation error.
    """


def _xml_text(value: Any) -> str:
    """
    Escape a value for safe use as XML element text.
    """

    return escape(
        str(value),
        {
            '"': "&quot;",
            "'": "&apos;",
        },
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
        raise WindowsUnattendError(
            "Jinja2 is required for Windows "
            "unattended-install rendering."
        ) from exc

    environment = Environment(
        loader=FileSystemLoader(
            str(template_dir)
        ),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )

    environment.filters[
        "xml"
    ] = _xml_text

    return environment


def _render_template(
    *,
    template_dir: Path,
    template_name: str,
    destination: Path,
    context: dict[str, Any],
) -> None:

    environment = (
        _load_jinja_environment(
            template_dir
        )
    )

    template = (
        environment.get_template(
            template_name
        )
    )

    rendered = template.render(
        **context
    )

    destination.write_text(
        rendered,
        encoding="utf-8",
    )


def _validate_xml(
    answer_file: Path,
) -> None:
    """
    Perform a basic XML well-formedness check before
    allowing Windows Setup to consume the file.
    """

    try:
        tree = ET.parse(
            answer_file
        )

    except ET.ParseError as exc:
        raise WindowsUnattendError(
            "Rendered Autounattend.xml "
            f"is invalid XML: {exc}"
        ) from exc

    root = tree.getroot()

    expected_root = (
        "{urn:schemas-microsoft-com:"
        "unattend}unattend"
    )

    if root.tag != expected_root:
        raise WindowsUnattendError(
            "Rendered answer file does not "
            "contain the expected Windows "
            "unattend root element."
        )


def _find_iso_builder() -> str:
    """
    Windows seed media requires a small ISO containing
    Autounattend.xml at the root.
    """

    xorriso = shutil.which(
        "xorriso"
    )

    if xorriso:
        return xorriso

    raise WindowsUnattendError(
        "xorriso is required to create "
        "Windows unattended-install media.\n"
        "Install it with:\n"
        "  sudo apt install xorriso"
    )


def _build_answer_iso(
    *,
    answer_file: Path,
    bootstrap_script: Path,
    bootstrap_config: Path,
    output_iso: Path,
    verbose: bool = False,
) -> None:

    xorriso = _find_iso_builder()

    output_iso.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output_iso.exists():
        output_iso.unlink()

    command = [
        xorriso,
        "-as",
        "mkisofs",

        "-output",
        str(output_iso),

        "-volid",
        "CRUCIBLE_WIN",

        "-joliet",
        "-rock",

        "-graft-points",

        (
            "Autounattend.xml="
            f"{answer_file}"
        ),

        (
            "bootstrap.ps1="
            f"{bootstrap_script}"
        ),

        (
            "crucible-bootstrap.json="
            f"{bootstrap_config}"
        ),
    ]

    if verbose:
        print(
            "+ "
            + " ".join(command)
        )

    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        raise WindowsUnattendError(
            "Failed to create Windows "
            "answer-file ISO.\n"
            f"Command: {' '.join(command)}\n"
            f"STDERR:\n"
            f"{result.stderr.strip()}"
        )

    if not output_iso.is_file():
        raise WindowsUnattendError(
            "ISO builder returned success "
            "but did not create:\n"
            f"{output_iso}"
        )


def build_unattend_iso(
    machine_manifest: dict[str, Any],
    profile: dict[str, Any],
    *,
    repo_root: Path,
    verbose: bool = False,
) -> Path:
    """
    Render Autounattend.xml for one Windows guest and
    package it as a tiny read-only ISO.

    Windows Setup discovers Autounattend.xml at the
    root of removable read-only media.
    """

    machine_name = str(
        machine_manifest.get(
            "name",
            "",
        )
    ).strip()

    if not machine_name:
        raise WindowsUnattendError(
            "Machine manifest has no name."
        )

    autoinstall = (
        machine_manifest.get(
            "autoinstall"
        )
    )

    if not isinstance(
        autoinstall,
        dict,
    ):
        raise WindowsUnattendError(
            "Machine manifest has no "
            "autoinstall mapping."
        )

    if not autoinstall.get(
        "enabled",
        False,
    ):
        raise WindowsUnattendError(
            "Windows unattended installation "
            "was requested but "
            "autoinstall.enabled is false."
        )

    identity = autoinstall.get(
        "identity",
        {},
    )

    username = str(
        identity.get(
            "username",
            "",
        )
    ).strip()

    password = str(
        identity.get(
            "password",
            "",
        )
    )

    realname = str(
        identity.get(
            "realname",
            "Crucible User",
        )
    ).strip()

    if not username:
        raise WindowsUnattendError(
            "Windows unattended installation "
            "requires identity.username."
        )

    if not password:
        raise WindowsUnattendError(
            "Windows unattended installation "
            "requires identity.password."
        )

    installer = profile.get(
        "installer",
        {},
    )

    bootstrap_script_setting = str(
        installer.get(
            "bootstrap_script",
            "",
        )
    ).strip()

    if not bootstrap_script_setting:
        raise WindowsUnattendError(
            "Windows OS profile does not define "
            "installer.bootstrap_script."
        )

    bootstrap_script = (
        repo_root
        / bootstrap_script_setting
    )

    if not bootstrap_script.is_file():
        raise WindowsUnattendError(
            "Windows bootstrap script "
            f"not found: {bootstrap_script}"
        )

    # ---------------------------------------------------------
    # Resolve selected Windows installation image
    #
    # Client Windows normally selects by image name.
    # Windows Server may select by WIM image index.
    # ---------------------------------------------------------

    install_image = autoinstall.get(
        "install_image",
        {},
    )

    if not isinstance(
        install_image,
        dict,
    ):
        raise WindowsUnattendError(
            "autoinstall.install_image "
            "must be a mapping."
        )

    # Optional WIM image index.

    image_index_raw = install_image.get(
        "index"
    )

    image_index = None

    if image_index_raw not in {
        None,
        "",
    }:

        try:
            image_index = int(
                image_index_raw
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise WindowsUnattendError(
                "Selected Windows image index "
                "is invalid."
            ) from exc

        if image_index < 1:
            raise WindowsUnattendError(
                "Selected Windows image index "
                "must be at least 1."
            )

    # Optional WIM image name.
    #
    # Fall back to the OS profile for Windows 10/11,
    # which still use fixed image names.

    image_name = str(
        install_image.get(
            "name",
            installer.get(
                "image_name",
                "",
            ),
        )
    ).strip()

    # At least one selector must exist.

    if (
        image_index is None
        and
        not image_name
    ):
        raise WindowsUnattendError(
            "No Windows installation image "
            "index or name was selected."
        )

    setup_product_key = str(
        install_image.get(
            "setup_product_key",
            installer.get(
                "setup_product_key",
                "",
            ),
        )
    ).strip()

    template_directory = str(
        installer.get(
            "template_directory",
            "installers/windows/templates",
        )
    )

    template_name = str(
        installer.get(
            "answer_file",
            "Autounattend.xml.j2",
        )
    )

    template_dir = (
        repo_root
        / template_directory
    )

    if not template_dir.is_dir():
        raise WindowsUnattendError(
            "Windows template directory "
            f"not found: {template_dir}"
        )

    template_path = (
        template_dir
        / template_name
    )

    if not template_path.is_file():
        raise WindowsUnattendError(
            "Windows answer-file template "
            f"not found: {template_path}"
        )

    locale = autoinstall.get(
        "locale",
        {},
    )

    autologon = autoinstall.get(
        "autologon",
        {},
    )

    disk = autoinstall.get(
        "disk",
        {},
    )

    network = machine_manifest.get(
        "network",
        {},
    )

    topology_interfaces = (
        network.get(
            "topology",
            [],
        )
    )

    internet_network = (
        network.get(
            "internet",
            {},
        )
    )

    internet_mac = str(
        internet_network.get(
            "mac_address",
            "",
        )
    ).strip()

    if not internet_mac:
        raise WindowsUnattendError(
            "Windows machine manifest "
            "is missing "
            "network.internet.mac_address."
        )

    management_network = network.get(
        "management",
        {},
    )

    management_address = str(
        management_network.get(
            "address",
            "",
        )
    ).strip()

    management_mac = str(
        management_network.get(
            "mac_address",
            "",
        )
    ).strip()

    if not management_address:
        raise WindowsUnattendError(
            "Windows machine manifest is missing "
            "network.management.address."
        )

    if not management_mac:
        raise WindowsUnattendError(
            "Windows machine manifest is missing "
            "network.management.mac_address."
        )

    try:
        management_interface = (
            ipaddress.ip_interface(
                management_address
            )
        )

    except ValueError as exc:
        raise WindowsUnattendError(
            "Invalid Windows management address: "
            f"{management_address}"
        ) from exc

    profile_management = profile.get(
        "management",
        {},
    )

    build_dir = (
        repo_root
        / ".crucible"
        / "generated"
        / "windows"
        / machine_name
    )

    build_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    bootstrap_config = (
        build_dir
        / "crucible-bootstrap.json"
    )

    guest_additions = (
        autoinstall.get(
            "guest_additions",
            {},
        )
    )

    if not isinstance(
        guest_additions,
        dict,
    ):
        raise WindowsUnattendError(
            "autoinstall.guest_additions "
            "must be a mapping."
        )

    guest_additions_enabled = bool(
        guest_additions.get(
            "enabled",
            True,
        )
    )

    bootstrap_config_data = {
        "schema_version": 2,

        "machine_name": machine_name,

        "management": {
            "address": str(
                management_interface.ip
            ),

            "prefix_length": int(
                management_interface.network.prefixlen
            ),

            "network": str(
                management_interface.network
            ),

            "mac_address": management_mac,
        },

        "winrm": {
            "transport": str(
                profile_management.get(
                    "transport",
                    "psrp",
                )
            ),

            "protocol": str(
                profile_management.get(
                    "protocol",
                    "https",
                )
            ),

            "port": int(
                profile_management.get(
                    "port",
                    5986,
                )
            ),

            "auth": str(
                profile_management.get(
                    "auth",
                    "ntlm",
                )
            ),
        },
        "internet": {
            "mac_address": (
                internet_mac
            ),
        },

        "topology": (
            topology_interfaces
        ),

        "routing": {
            "internet_metric": (
                CRUCIBLE_NAT_ROUTE_METRIC
            ),
            "topology_metric": (
                TOPOLOGY_ROUTE_METRIC
            ),
        },

        "guest_additions": {
            "enabled": (
                guest_additions_enabled
            ),
        },
    }

    bootstrap_config.write_text(
        json.dumps(
            bootstrap_config_data,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    answer_file = (
        build_dir
        / "Autounattend.xml"
    )

    context = {
        "computer_name": machine_name,

        "image_name": image_name,

        "image_index": (
            image_index
        ),

        "setup_product_key": (
            setup_product_key
        ),

        "set_administrator_password": bool(
            installer.get(
                "set_administrator_password",
                False,
            )
        ),
        
        "realname": realname,
        "username": username,
        "password": password,

        "organization": str(
            autoinstall.get(
                "organization",
                "Operation Crucible",
            )
        ),

        "ui_language": str(
            locale.get(
                "ui_language",
                "en-US",
            )
        ),

        "input_locale": str(
            locale.get(
                "input_locale",
                "en-US",
            )
        ),

        "system_locale": str(
            locale.get(
                "system_locale",
                "en-CA",
            )
        ),

        "user_locale": str(
            locale.get(
                "user_locale",
                "en-CA",
            )
        ),

        "timezone": str(
            autoinstall.get(
                "timezone",
                "Eastern Standard Time",
            )
        ),

        "disk_id": int(
            disk.get(
                "id",
                0,
            )
        ),

        "autologon_enabled": bool(
            autologon.get(
                "enabled",
                True,
            )
        ),

        "autologon_count": int(
            autologon.get(
                "count",
                1,
            )
        ),
    }

    _render_template(
        template_dir=template_dir,
        template_name=template_name,
        destination=answer_file,
        context=context,
    )

    _validate_xml(
        answer_file
    )

    output_iso = (
        build_dir
        / f"{machine_name}-unattend.iso"
    )

    _build_answer_iso(
        answer_file=answer_file,
        bootstrap_script=bootstrap_script,
        bootstrap_config=bootstrap_config,
        output_iso=output_iso,
        verbose=verbose,
    )

    return output_iso