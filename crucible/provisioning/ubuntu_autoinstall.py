from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
import base64
import yaml


class UbuntuAutoinstallError(RuntimeError):
    """Expected Ubuntu autoinstall seed-generation error."""


def _yaml_string(value: Any) -> str:
    """
    JSON string literals are also valid YAML string literals.
    This gives templates predictable quoting without hand-escaping.
    """
    return json.dumps(str(value))


def _load_jinja_environment(template_dir: Path):
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ModuleNotFoundError as exc:
        raise UbuntuAutoinstallError(
            "Jinja2 is required for autoinstall template rendering. "
            "Install project dependencies with: "
            "python3 -m pip install -r requirements.txt"
        ) from exc

    environment = Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )

    environment.filters["yaml_string"] = _yaml_string

    return environment


def _render_template(
    template_dir: Path,
    template_name: str,
    destination: Path,
    context: dict[str, Any],
) -> None:
    environment = _load_jinja_environment(template_dir)
    template = environment.get_template(template_name)

    rendered = template.render(**context)

    destination.write_text(
        rendered,
        encoding="utf-8",
    )


def _validate_rendered_user_data(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    if not text.startswith("#cloud-config"):
        raise UbuntuAutoinstallError(
            f"{path} does not begin with '#cloud-config'."
        )

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise UbuntuAutoinstallError(
            f"Rendered user-data is not valid YAML: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise UbuntuAutoinstallError(
            "Rendered user-data must contain a YAML mapping."
        )

    autoinstall = data.get("autoinstall")

    if not isinstance(autoinstall, dict):
        raise UbuntuAutoinstallError(
            "Rendered user-data is missing the top-level "
            "'autoinstall:' mapping."
        )

    if autoinstall.get("version") != 1:
        raise UbuntuAutoinstallError(
            "Rendered autoinstall version must be 1."
        )

    identity = autoinstall.get("identity")

    if not isinstance(identity, dict):
        raise UbuntuAutoinstallError(
            "Rendered autoinstall configuration is missing identity."
        )

    for field in ("hostname", "username", "password"):
        if not identity.get(field):
            raise UbuntuAutoinstallError(
                f"Rendered identity is missing required field: {field}"
            )


def _find_iso_builder() -> tuple[str, str]:
    xorriso = shutil.which("xorriso")

    if xorriso:
        return ("xorriso", xorriso)

    genisoimage = shutil.which("genisoimage")

    if genisoimage:
        return ("genisoimage", genisoimage)

    mkisofs = shutil.which("mkisofs")

    if mkisofs:
        return ("mkisofs", mkisofs)

    raise UbuntuAutoinstallError(
        "No ISO creation utility was found. Install xorriso with:\n"
        "  sudo apt install xorriso"
    )


def _build_seed_iso(
    *,
    user_data: Path,
    meta_data: Path,
    output_iso: Path,
    verbose: bool,
) -> None:
    kind, executable = _find_iso_builder()

    output_iso.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if output_iso.exists():
        output_iso.unlink()

    if kind == "xorriso":
        command = [
            executable,
            "-as",
            "mkisofs",
            "-output",
            str(output_iso),
            "-volid",
            "CIDATA",
            "-joliet",
            "-rock",
            str(user_data),
            str(meta_data),
        ]
    else:
        command = [
            executable,
            "-output",
            str(output_iso),
            "-volid",
            "CIDATA",
            "-joliet",
            "-rock",
            str(user_data),
            str(meta_data),
        ]

    if verbose:
        print("+ " + " ".join(command))

    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        raise UbuntuAutoinstallError(
            "Failed to create NoCloud seed ISO.\n"
            f"Command: {' '.join(command)}\n"
            f"STDERR:\n{result.stderr.strip()}"
        )

    if not output_iso.is_file():
        raise UbuntuAutoinstallError(
            f"ISO builder returned success but did not create: "
            f"{output_iso}"
        )


def build_seed_iso(
    machine_manifest: dict[str, Any],
    *,
    repo_root: Path,
    verbose: bool = False,
) -> Path:
    """
    Render Ubuntu NoCloud user-data/meta-data from a machine manifest
    and package them into images/generated/<vm>-seed.iso.
    """
    machine_name = str(machine_manifest.get("name", "")).strip()

    if not machine_name:
        raise UbuntuAutoinstallError(
            "Machine manifest has no name."
        )

    autoinstall = machine_manifest.get("autoinstall")

    if not isinstance(autoinstall, dict):
        raise UbuntuAutoinstallError(
            "Machine manifest has no autoinstall mapping."
        )

    if not autoinstall.get("enabled", False):
        raise UbuntuAutoinstallError(
            "Autoinstall seed generation was requested but "
            "autoinstall.enabled is false."
        )

    identity = autoinstall.get("identity", {})
    keyboard = autoinstall.get("keyboard", {})
    storage = autoinstall.get("storage", {})
    ssh = autoinstall.get("ssh", {})

    password_hash = str(
        identity.get("password_hash", "")
    ).strip()

    if not password_hash:
        raise UbuntuAutoinstallError(
            "autoinstall.identity.password_hash is required."
        )

    template_dir = (
        repo_root
        / "installers"
        / "linux"
        / "ubuntu"
        / "templates"
    )

    if not template_dir.is_dir():
        raise UbuntuAutoinstallError(
            f"Ubuntu template directory not found: {template_dir}"
        )

    build_dir = (
        repo_root
        / ".crucible"
        / "generated"
        / "autoinstall"
        / machine_name
    )

    build_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    user_data_path = build_dir / "user-data"
    meta_data_path = build_dir / "meta-data"

    bootstrap_path = (
        repo_root
        / "installers"
        / "linux"
        / "common"
        / "bootstrap.sh"
    )

    if not bootstrap_path.is_file():
        raise UbuntuAutoinstallError(
            f"Linux bootstrap script not found: "
            f"{bootstrap_path}"
        )

    bootstrap_bytes = bootstrap_path.read_bytes()

    bootstrap_base64 = base64.b64encode(
        bootstrap_bytes
    ).decode("ascii")

    late_commands = [
        (
            "printf '%s' "
            f"'{bootstrap_base64}' "
            "| base64 -d "
            "> /target/usr/local/sbin/"
            "crucible-bootstrap.sh"
        ),
        (
            "chmod 0755 "
            "/target/usr/local/sbin/"
            "crucible-bootstrap.sh"
        ),
        (
            "curtin in-target -- "
            "/usr/local/sbin/"
            "crucible-bootstrap.sh"
        ),
    ]

    context = {
        "instance_id": f"crucible-{machine_name}",
        "hostname": autoinstall.get(
            "hostname",
            machine_name,
        ),
        "realname": identity.get(
            "realname",
            "Crucible User",
        ),
        "username": identity.get(
            "username",
            "crucible",
        ),
        "password_hash": password_hash,
        "locale": autoinstall.get(
            "locale",
            "en_US.UTF-8",
        ),
        "timezone": autoinstall.get(
            "timezone",
            "Etc/UTC",
        ),
        "keyboard_layout": keyboard.get(
            "layout",
            "us",
        ),
        "keyboard_variant": keyboard.get(
            "variant",
            "",
        ),
        "storage_layout": storage.get(
            "layout",
            "direct",
        ),
        "ssh_install_server": bool(
            ssh.get("install_server", True)
        ),
        "ssh_allow_password": bool(
            ssh.get("allow_password", True)
        ),
        "ssh_authorized_keys": list(
            ssh.get("authorized_keys", [])
        ),
        "updates": autoinstall.get(
            "updates",
            "security",
        ),
        "shutdown": autoinstall.get(
            "shutdown",
            "reboot",
        ),
        "late_commands": late_commands,
    }

    _render_template(
        template_dir,
        "user-data.j2",
        user_data_path,
        context,
    )

    _render_template(
        template_dir,
        "meta-data.j2",
        meta_data_path,
        context,
    )

    _validate_rendered_user_data(
        user_data_path
    )

    output_iso = (
        repo_root
        / "images"
        / "generated"
        / f"{machine_name}-seed.iso"
    )

    _build_seed_iso(
        user_data=user_data_path,
        meta_data=meta_data_path,
        output_iso=output_iso,
        verbose=verbose,
    )

    return output_iso
