from __future__ import annotations

import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class SshIdentityError(RuntimeError):
    """Raised when Crucible cannot create or load an SSH identity."""


@dataclass(frozen=True)
class SshIdentity:
    machine_name: str
    instance_serial: str
    directory: Path
    private_key: Path
    public_key: Path
    known_hosts: Path
    public_key_text: str


def generate_instance_serial() -> str:
    """
    Generate a human-readable unique serial for one
    forged VM instance.

    Example:

        CRU-A19F82C44310
    """

    return (
        "CRU-"
        + secrets.token_hex(
            6
        ).upper()
    )


def identity_directory(
    repo_root: Path,
    machine_name: str,
    instance_serial: str,
) -> Path:
    return (
        repo_root
        / ".crucible"
        / "ssh"
        / "machines"
        / (
            f"{machine_name}-"
            f"{instance_serial}"
        )
    )

def reset_machine_known_hosts(
    identity: SshIdentity,
) -> None:
    """
    Reset the permanent host-key trust database for a VM
    immediately before establishing its final installed-OS
    SSH identity.
    """

    identity.known_hosts.write_text(
        "",
        encoding="utf-8",
    )

    identity.known_hosts.chmod(
        0o600
    )

def create_machine_ssh_identity(
    *,
    repo_root: Path,
    machine_name: str,
    instance_serial: str,
) -> SshIdentity:
    """
    Create the dedicated controller-side SSH identity
    for one Crucible VM instance.
    """

    ssh_keygen = shutil.which(
        "ssh-keygen"
    )

    if ssh_keygen is None:
        raise SshIdentityError(
            "ssh-keygen is required to create "
            "Crucible management identities."
        )

    directory = identity_directory(
        repo_root,
        machine_name,
        instance_serial,
    )

    if directory.exists():
        raise SshIdentityError(
            "SSH identity directory already exists "
            "for instance "
            f"{instance_serial}: {directory}"
        )

    directory.mkdir(
        parents=True,
        mode=0o700,
    )

    directory.chmod(
        0o700
    )

    private_key = (
        directory
        / "id_ed25519"
    )

    public_key = (
        directory
        / "id_ed25519.pub"
    )

    known_hosts = (
        directory
        / "known_hosts"
    )

    comment = (
        "operation-crucible:"
        f"{machine_name}:"
        f"{instance_serial}"
    )

    result = subprocess.run(
        [
            ssh_keygen,
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            comment,
            "-f",
            str(
                private_key
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        raise SshIdentityError(
            "Could not generate Crucible SSH key:\n"
            + result.stderr.strip()
        )

    if (
        not private_key.is_file()
        or
        not public_key.is_file()
    ):
        raise SshIdentityError(
            "ssh-keygen returned success but "
            "the expected key files were not created."
        )

    private_key.chmod(
        0o600
    )

    public_key.chmod(
        0o644
    )

    known_hosts.touch(
        mode=0o600,
        exist_ok=False,
    )

    known_hosts.chmod(
        0o600
    )

    public_key_text = (
        public_key.read_text(
            encoding="utf-8"
        ).strip()
    )

    if not public_key_text.startswith(
        "ssh-ed25519 "
    ):
        raise SshIdentityError(
            "Generated public key is not "
            "an Ed25519 SSH public key."
        )

    return SshIdentity(
        machine_name=machine_name,
        instance_serial=instance_serial,
        directory=directory,
        private_key=private_key,
        public_key=public_key,
        known_hosts=known_hosts,
        public_key_text=public_key_text,
    )

def load_machine_ssh_identity(
    *,
    repo_root: Path,
    machine_name: str,
    instance_serial: str,
) -> SshIdentity:
    """
    Load an already-created per-instance SSH identity.
    """

    directory = (
        identity_directory(
            repo_root,
            machine_name,
            instance_serial,
        )
    )

    private_key = (
        directory
        / "id_ed25519"
    )

    public_key = (
        directory
        / "id_ed25519.pub"
    )

    known_hosts = (
        directory
        / "known_hosts"
    )

    for path in (
        private_key,
        public_key,
        known_hosts,
    ):
        if not path.is_file():
            raise SshIdentityError(
                "Incomplete Crucible SSH "
                f"identity: missing {path}"
            )

    private_key.chmod(
        0o600
    )

    known_hosts.chmod(
        0o600
    )

    public_key_text = (
        public_key.read_text(
            encoding="utf-8"
        ).strip()
    )

    return SshIdentity(
        machine_name=machine_name,
        instance_serial=instance_serial,
        directory=directory,
        private_key=private_key,
        public_key=public_key,
        known_hosts=known_hosts,
        public_key_text=public_key_text,
    )