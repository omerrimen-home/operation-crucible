#!/usr/bin/env python3

"""
Operation Crucible
VirtualBox hypervisor provider.

This module is responsible ONLY for virtual infrastructure:

    - Detecting VirtualBox / VBoxManage
    - Discovering VirtualBox capabilities
    - Creating and deleting VMs
    - Configuring virtual hardware
    - Creating and attaching virtual disks
    - Attaching installation / bootstrap ISO images
    - Configuring virtual NICs
    - Creating a Crucible host-only management interface
    - VM power control
    - Snapshots
    - TPM / EFI / Secure Boot configuration

It is deliberately NOT responsible for:

    - Ubuntu autoinstall generation
    - Windows Autounattend.xml generation
    - Kali preseed generation
    - Ansible configuration
    - Lab-specific operating-system configuration

Those responsibilities belong to other Crucible layers.
"""

from __future__ import annotations
import ipaddress
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from crucible.networking.management import (
    MANAGEMENT_HOST_IP as CRUCIBLE_MANAGEMENT_HOST_IP,
    MANAGEMENT_NETMASK as CRUCIBLE_MANAGEMENT_NETMASK,
)

# ---------------------------------------------------------------------------
# Repository paths
# ---------------------------------------------------------------------------

# operation-crucible/
# └── crucible/
#     └── hypervisors/
#         └── virtualbox.py

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_VM_BASE_FOLDER = REPO_ROOT / ".crucible" / "vms"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VirtualBoxError(RuntimeError):
    """Base exception for all VirtualBox provider failures."""


class VirtualBoxNotInstalledError(VirtualBoxError):
    """Raised when VBoxManage cannot be found."""


class VBoxCommandError(VirtualBoxError):
    """Raised when VBoxManage returns a non-zero exit status."""

    def __init__(
        self,
        command: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

        message = (
            f"VBoxManage command failed with exit code {returncode}\n"
            f"Command: {' '.join(command)}"
        )

        if stdout.strip():
            message += f"\nSTDOUT:\n{stdout.strip()}"

        if stderr.strip():
            message += f"\nSTDERR:\n{stderr.strip()}"

        super().__init__(message)


class VMAlreadyExistsError(VirtualBoxError):
    """Raised when attempting to create an existing VM."""


class VMNotFoundError(VirtualBoxError):
    """Raised when a requested VM does not exist."""


class VMStateError(VirtualBoxError):
    """Raised when a VM is in an incompatible state."""


class VirtualBoxConfigurationError(VirtualBoxError):
    """Raised for invalid provider configuration."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VBoxVersion:
    major: int
    minor: int
    patch: int
    raw: str

    def at_least(
        self,
        major: int,
        minor: int = 0,
        patch: int = 0,
    ) -> bool:
        return (self.major, self.minor, self.patch) >= (
            major,
            minor,
            patch,
        )


@dataclass(frozen=True)
class VBoxVM:
    name: str
    uuid: str


@dataclass
class VBoxResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class HostOnlyInterface:
    name: str
    ip_address: str | None
    network_mask: str | None
    status: str | None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class VirtualBoxProvider:
    """
    VirtualBox implementation of the Operation Crucible hypervisor layer.

    All VBoxManage interaction should eventually pass through this class
    rather than being scattered throughout Crucible.
    """

    MANAGEMENT_NETWORK_NAME = "CRUCIBLE-MGMT"

    MANAGEMENT_IP = (
        CRUCIBLE_MANAGEMENT_HOST_IP
    )

    MANAGEMENT_NETMASK = (
        CRUCIBLE_MANAGEMENT_NETMASK
    )

    LEGACY_MANAGEMENT_IP = (
        "172.31.255.1"
    )

    LEGACY_MANAGEMENT_NETMASK = (
        "255.255.255.0"
)

    DEFAULT_STORAGE_CONTROLLER = "SATA Controller"
    DEFAULT_STORAGE_CONTROLLER_TYPE = "IntelAHCI"

    def __init__(
        self,
        *,
        vboxmanage: str | None = None,
        vm_base_folder: str | Path | None = None,
        dry_run: bool = False,
        verbose: bool = False,
        command_timeout: int = 120,
    ) -> None:

        self.binary = (
            vboxmanage
            or shutil.which("VBoxManage")
            or shutil.which("vboxmanage")
        )

        if self.binary is None:
            raise VirtualBoxNotInstalledError(
                "VBoxManage was not found in PATH. "
                "Confirm that VirtualBox is installed and that "
                "VBoxManage is accessible from the shell."
            )

        self.binary = os.path.abspath(self.binary)

        self.vm_base_folder = Path(
            vm_base_folder or DEFAULT_VM_BASE_FOLDER
        ).expanduser().resolve()

        self.vm_base_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.dry_run = dry_run
        self.verbose = verbose
        self.command_timeout = command_timeout

        self._version: VBoxVersion | None = None
        self._ostype_cache: set[str] | None = None
    
    def start_ubuntu_autoinstall(
        self,
        name: str,
        *,
        headless: bool = False,
        boot_delay_seconds: float = 3.0,
        flavor: str = "server",
    ) -> None:
        """
        Start an Ubuntu installer and automatically add the
        'autoinstall' kernel argument at the GRUB boot menu.

        Server and Desktop currently have slightly different
        kernel command lines, so their edit sequences differ.

        The actual autoinstall configuration comes from the
        attached NoCloud CIDATA seed ISO.
        """

        self.start_vm(
            name,
            headless=headless,
        )
        print("      -> waiting for Ubuntu GRUB")
        # Give VirtualBox EFI enough time to reach the Ubuntu GRUB menu.
        time.sleep(boot_delay_seconds)
        print("      -> entering GRUB edit mode")
        # Edit the selected "Try or Install Ubuntu Server" entry.
        self._run(
            [
                "controlvm",
                name,
                "keyboardputstring",
                "e",
            ]
        )

        time.sleep(0.5)
        print("      -> injecting autoinstall kernel argument")
        # GRUB's edit view normally contains:
        #
        #   setparams ...
        #   set gfxpayload=keep
        #   linux /casper/vmlinuz ---
        #   initrd /casper/initrd
        #
        # Move to the linux line.
        for _ in range(3):
            self._run(
                [
                    "controlvm",
                    name,
                    "keyboardputscancode",
                    "e0",
                    "50",
                    "e0",
                    "d0",
                ]
            )

        # Move to the end of:
        #
        # linux /casper/vmlinuz ---
        self._run(
            [
                "controlvm",
                name,
                "keyboardputscancode",
                "e0",
                "4f",
                "e0",
                "cf",
            ]
        )

        if flavor == "server":

            # Known-good Ubuntu Server path.
            #
            # Server's kernel line ends with:
            #
            #   ---
            #
            # Remove it and replace it with the
            # autoinstall arguments.

            for _ in range(4):
                self._run(
                    [
                        "controlvm",
                        name,
                        "keyboardputscancode",
                        "0e",
                        "8e",
                    ]
                )

            self._run(
                [
                    "controlvm",
                    name,
                    "keyboardputstring",
                    "autoinstall ds=nocloud",
                ]
            )

        elif flavor == "desktop":

            # Ubuntu Desktop 26.04's kernel line
            # contains:
            #
            #   --- quiet splash
            #
            # Preserve the existing arguments and
            # simply append the zero-touch flag.
            #
            # The attached CIDATA volume supplies
            # the NoCloud configuration.

            self._run(
                [
                    "controlvm",
                    name,
                    "keyboardputstring",
                    " autoinstall",
                ]
            )

        else:
            raise VirtualBoxConfigurationError(
                f"Unsupported Ubuntu flavor "
                f"for autoinstall boot automation: "
                f"{flavor}"
            )

        time.sleep(0.25)

        # Ctrl+X tells GRUB to boot the edited entry.
        self._run(
            [
                "controlvm",
                name,
                "keyboardputscancode",
                "1d",  # Ctrl down
                "2d",  # X down
                "ad",  # X up
                "9d",  # Ctrl up
            ]
        )

    def start_kali_preseed_install(
        self,
        name: str,
        *,
        preseed_url: str,
        installer_interface: str,
        headless: bool = False,
        boot_delay_seconds: float = 3.0,
    ) -> None:
        """
        Start Kali's Debian Installer and replace the
        selected UEFI GRUB kernel command line with
        Crucible's unattended-install parameters.

        The preseed itself is supplied by a temporary
        HTTP service reachable through VirtualBox NAT.
        """

        if not preseed_url.startswith(
            "http://"
        ):
            raise VirtualBoxConfigurationError(
                "Kali preseed URL must use HTTP."
            )

        if any(
            character.isspace()
            for character in preseed_url
        ):
            raise VirtualBoxConfigurationError(
                "Kali preseed URL may not "
                "contain whitespace."
            )

        kernel_command = (
            "linux /install.amd/vmlinuz "
            "net.ifnames=0 "
            "auto=true "
            "priority=critical "
            f"interface={installer_interface} "
            "debconf/frontend=noninteractive "
            f"preseed/url={preseed_url}"
        )

        self.start_vm(
            name,
            headless=headless,
        )

        print(
            "      -> waiting for Kali GRUB"
        )

        time.sleep(
            boot_delay_seconds
        )

        print(
            "      -> entering Kali GRUB edit mode"
        )

        # Edit the currently selected Kali installer
        # boot entry.
        self._run(
            [
                "controlvm",
                name,
                "keyboardputstring",
                "e",
            ]
        )

        time.sleep(1.0)

        print(
            "      -> locating Kali kernel line"
        )

        # Kali's current UEFI GRUB entry has the linux
        # command three lines below the initial cursor.
        #
        # Kali's own Packer automation performs the same
        # three-down navigation before replacing the line.
        for _ in range(3):
            self._run(
                [
                    "controlvm",
                    name,
                    "keyboardputscancode",

                    "e0",
                    "50",

                    "e0",
                    "d0",
                ]
            )

        time.sleep(0.25)

        # Ctrl+A
        #
        # Move to the beginning of the current GRUB line.
        self._run(
            [
                "controlvm",
                name,
                "keyboardputscancode",

                "1d",  # Ctrl down
                "1e",  # A down
                "9e",  # A up
                "9d",  # Ctrl up
            ]
        )

        time.sleep(0.1)

        # Ctrl+K
        #
        # Delete from the cursor through the end of the
        # current line. Since Ctrl+A moved us to column
        # zero, this replaces the whole kernel line.
        self._run(
            [
                "controlvm",
                name,
                "keyboardputscancode",

                "1d",  # Ctrl down
                "25",  # K down
                "a5",  # K up
                "9d",  # Ctrl up
            ]
        )

        time.sleep(0.1)

        print(
            "      -> injecting Kali unattended "
            "installer arguments"
        )

        self._run(
            [
                "controlvm",
                name,
                "keyboardputstring",
                kernel_command,
            ]
        )

        time.sleep(0.25)

        print(
            "      -> booting Kali installer"
        )

        # F10 boots the edited GRUB entry.
        self._run(
            [
                "controlvm",
                name,
                "keyboardputscancode",

                "44",  # F10 down
                "c4",  # F10 up
            ]
        )

    def start_windows_unattended_install(
            self,
            name: str,
            *,
            headless: bool = False,
            boot_delay_seconds: float = 3.0,
        ) -> None:
            """
            Start a Windows installer VM and automatically
            acknowledge the Microsoft installation DVD's:

                Press any key to boot from CD or DVD...

            prompt.

            The key is injected only during the initial VM start.
            Crucible deliberately does not inject additional keys
            after later Windows Setup reboots, allowing those DVD
            prompts to time out and the VM to continue booting from
            its installed virtual disk.
            """

            self.start_vm(
                name,
                headless=headless,
            )

            print(
                "      -> waiting for Windows DVD boot prompt"
            )

            time.sleep(
                boot_delay_seconds
            )

            print(
                "      -> acknowledging Windows DVD boot prompt"
            )

            # Set-1 PC keyboard scancodes:
            #
            #   0x39 = Space key down
            #   0xB9 = Space key up
            #
            # A raw scancode is preferable here to keyboardputstring
            # because this input is consumed by pre-OS EFI/DVD boot
            # code rather than by an operating system.
            self._run(
                [
                    "controlvm",
                    name,
                    "keyboardputscancode",
                    "39",
                    "b9",
                ]
            )

            print(
                "      -> Windows installer boot requested"
            )

        # ------------------------------------------------------------------
        # VBoxManage execution
        # ------------------------------------------------------------------

    def _run(
        self,
        args: Iterable[str],
        *,
        check: bool = True,
        timeout: int | None = None,
    ) -> VBoxResult:

        command = [self.binary, *[str(arg) for arg in args]]

        if self.verbose or self.dry_run:
            print("+", " ".join(command))

        if self.dry_run:
            return VBoxResult(
                command=command,
                returncode=0,
                stdout="",
                stderr="",
            )

        environment = os.environ.copy()

        # This makes VBoxManage output more predictable for parsers.
        environment["LC_ALL"] = "C"
        environment["LANG"] = "C"

        try:
            process = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=timeout or self.command_timeout,
                env=environment,
            )

        except subprocess.TimeoutExpired as exc:
            raise VirtualBoxError(
                f"VBoxManage command timed out: "
                f"{' '.join(command)}"
            ) from exc

        except OSError as exc:
            raise VirtualBoxError(
                f"Could not execute VBoxManage: {exc}"
            ) from exc

        result = VBoxResult(
            command=command,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
        )

        if check and result.returncode != 0:
            raise VBoxCommandError(
                result.command,
                result.returncode,
                result.stdout,
                result.stderr,
            )

        return result

    # ------------------------------------------------------------------
    # Environment detection
    # ------------------------------------------------------------------

    def available(self) -> bool:
        result = self._run(
            ["--version"],
            check=False,
        )

        return result.returncode == 0

    def version(self) -> VBoxVersion:
        if self._version is not None:
            return self._version

        result = self._run(["--version"])

        raw = result.stdout.strip()

        # Common outputs resemble:
        #
        # 7.2.0r170228
        # 7.1.12r169651
        #
        match = re.match(
            r"(?P<major>\d+)"
            r"\.(?P<minor>\d+)"
            r"(?:\.(?P<patch>\d+))?",
            raw,
        )

        if not match:
            raise VirtualBoxError(
                f"Unable to parse VirtualBox version: {raw!r}"
            )

        self._version = VBoxVersion(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch") or 0),
            raw=raw,
        )

        return self._version

    # ------------------------------------------------------------------
    # Guest OS types
    # ------------------------------------------------------------------

    def list_os_types(self) -> set[str]:
        result = self._run(
            ["list", "ostypes"]
        )

        os_types: set[str] = set()

        for line in result.stdout.splitlines():
            match = re.match(
                r"^\s*ID(?:\s*/\s*Description)?:\s*(.+?)\s*$",
                line,
            )

            if not match:
                continue

            value = match.group(1).strip()

            os_type_id = (
                value
                .split(" -- ", 1)[0]
                .strip()
            )

            if os_type_id:
                os_types.add(os_type_id)

        return os_types

    def resolve_os_type(
        self,
        candidates: Iterable[str],
    ) -> str:

        available = self.list_os_types()

        candidate_list = list(candidates)

        for candidate in candidate_list:
            if candidate in available:
                return candidate

        raise VirtualBoxConfigurationError(
            "None of the requested VirtualBox OS types exist "
            "on this host.\n"
            f"Requested: {candidate_list}"
        )

    # ------------------------------------------------------------------
    # VM discovery
    # ------------------------------------------------------------------

    def list_vms(self) -> list[VBoxVM]:
        result = self._run(
            ["list", "vms"]
        )

        machines: list[VBoxVM] = []

        pattern = re.compile(
            r'^"(?P<name>.*)" '
            r'\{(?P<uuid>[0-9a-fA-F-]+)\}$'
        )

        for line in result.stdout.splitlines():
            match = pattern.match(line.strip())

            if not match:
                continue

            machines.append(
                VBoxVM(
                    name=match.group("name"),
                    uuid=match.group("uuid"),
                )
            )

        return machines

    def vm_exists(self, name: str) -> bool:
        return any(
            machine.name == name
            for machine in self.list_vms()
        )

    def require_vm(self, name: str) -> None:
        if not self.vm_exists(name):
            raise VMNotFoundError(
                f"VirtualBox VM does not exist: {name}"
            )

    # ------------------------------------------------------------------
    # Machine-readable VM information
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_machine_readable(
        output: str,
    ) -> dict[str, str]:

        values: dict[str, str] = {}

        for raw_line in output.splitlines():
            line = raw_line.strip()

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            key = key.strip()
            value = value.strip()

            if (
                len(value) >= 2
                and value.startswith('"')
                and value.endswith('"')
            ):
                value = value[1:-1]

            values[key] = value

        return values

    def vm_info(
        self,
        name: str,
    ) -> dict[str, str]:

        self.require_vm(name)

        result = self._run(
            [
                "showvminfo",
                name,
                "--machinereadable",
            ]
        )

        return self._parse_machine_readable(
            result.stdout
        )

    def vm_state(self, name: str) -> str:
        return self.vm_info(name).get(
            "VMState",
            "unknown",
        )

    def is_running(self, name: str) -> bool:
        return self.vm_state(name) == "running"

    def require_powered_off(
        self,
        name: str,
    ) -> None:

        state = self.vm_state(name)

        allowed = {
            "poweroff",
            "aborted",
        }

        if state not in allowed:
            raise VMStateError(
                f"VM '{name}' must be powered off. "
                f"Current state: {state}"
            )

    # ------------------------------------------------------------------
    # VM creation
    # ------------------------------------------------------------------

    def create_vm(
        self,
        *,
        name: str,
        os_type_candidates: Iterable[str],
        cpus: int,
        memory_mb: int,
        firmware: str = "efi",
        chipset: str = "piix3",
        graphics_controller: str = "vmsvga",
        vram_mb: int = 32,
        ioapic: bool = True,
        paravirt_provider: str = "default",
        rtc_utc: bool = True,
        tpm_type: str = "none",
        accelerate_3d: bool = False,
    ) -> None:

        if self.vm_exists(name):
            raise VMAlreadyExistsError(
                f"VirtualBox VM already exists: {name}"
            )

        if cpus < 1:
            raise ValueError("cpus must be >= 1")

        if memory_mb < 256:
            raise ValueError(
                "memory_mb must be >= 256"
            )

        os_type = self.resolve_os_type(
            os_type_candidates
        )

        create_args = [
            "createvm",
            "--name",
            name,
            "--ostype",
            os_type,
            "--basefolder",
            str(self.vm_base_folder),
            "--register",
        ]

        # VirtualBox 7.2 explicitly exposes platform architecture
        # in createvm. Avoid passing it to older releases.
        if self.version().at_least(7, 2):
            create_args.extend(
                [
                    "--platform-architecture",
                    "x86",
                ]
            )

        self._run(create_args)

        try:
            self._run(
                [
                    "modifyvm",
                    name,

                    "--cpus",
                    str(cpus),

                    "--memory",
                    str(memory_mb),

                    "--vram",
                    str(vram_mb),

                    "--firmware",
                    firmware,

                    "--chipset",
                    chipset,

                    "--ioapic",
                    "on" if ioapic else "off",

                    "--graphicscontroller",
                    graphics_controller,

                    "--accelerate-3d",
                    "on" if accelerate_3d else "off",
                    
                    "--paravirtprovider",
                    paravirt_provider,

                    "--rtcuseutc",
                    "on" if rtc_utc else "off",

                    "--tpm-type",
                    tpm_type,

                    # Disable things we do not need during
                    # automated provisioning.
                    "--audio-enabled",
                    "off",

                    "--clipboard-mode",
                    "disabled",

                    "--drag-and-drop",
                    "disabled",
                ]
            )

        except Exception:
            # Avoid leaving a half-created VM behind if the
            # hardware configuration fails.
            try:
                self.delete_vm(
                    name,
                    force=True,
                )
            except Exception:
                pass

            raise

    # ------------------------------------------------------------------
    # Complete VM creation from an OS profile
    # ------------------------------------------------------------------

    def create_vm_from_profile(
        self,
        *,
        name: str,
        profile: dict[str, Any],
        cpus: int | None = None,
        memory_mb: int | None = None,
        disk_gb: int | None = None,
        firmware: str | None = None,
        graphics_controller: str | None = None,
        vram_mb: int | None = None,
        accelerate_3d: bool | None = None,
    ) -> Path:

        defaults = profile.get(
            "defaults",
            {},
        )

        vbox = profile.get(
            "virtualbox",
            {},
        )

        graphics = vbox.get(
            "graphics",
            {},
        )

        storage = vbox.get(
            "storage",
            {},
        )

        security = vbox.get(
            "security",
            {},
        )

        self.create_vm(
            name=name,
            os_type_candidates=vbox.get(
                "ostype_candidates",
                ["Other_64"],
            ),
            cpus=int(
                cpus
                if cpus is not None
                else defaults.get("cpus", 2)
            ),
            memory_mb=int(
                memory_mb
                if memory_mb is not None
                else defaults.get(
                    "memory_mb",
                    2048,
                )
            ),
            chipset=vbox.get(
                "chipset",
                "piix3",
            ),
            firmware=(
                firmware
                if firmware is not None
                else vbox.get(
                    "firmware",
                    "efi",
                )
            ),

            graphics_controller=(
                graphics_controller
                if graphics_controller is not None
                else graphics.get(
                    "controller",
                    "vmsvga",
                )
            ),

            vram_mb=int(
                vram_mb
                if vram_mb is not None
                else graphics.get(
                    "vram_mb",
                    32,
                )
            ),

            accelerate_3d=bool(
                accelerate_3d
                if accelerate_3d is not None
                else graphics.get(
                    "accelerate_3d",
                    False,
                )
            ),
            ioapic=bool(
                vbox.get(
                    "ioapic",
                    True,
                )
            ),
            paravirt_provider=vbox.get(
                "paravirt_provider",
                "default",
            ),
            rtc_utc=bool(
                vbox.get(
                    "rtc_utc",
                    True,
                )
            ),
            tpm_type=str(
                security.get(
                    "tpm",
                    "none",
                )
            ),
        )

        controller_name = storage.get(
            "controller_name",
            self.DEFAULT_STORAGE_CONTROLLER,
        )

        controller_type = storage.get(
            "controller_type",
            self.DEFAULT_STORAGE_CONTROLLER_TYPE,
        )

        self.ensure_sata_controller(
            name,
            controller_name=controller_name,
            controller_type=controller_type,
            port_count=int(
                storage.get(
                    "port_count",
                    4,
                )
            ),
        )

        requested_disk_gb = int(
            disk_gb
            if disk_gb is not None
            else defaults.get(
                "disk_gb",
                32,
            )
        )

        disk_path = self.default_disk_path(
            name
        )

        self.create_disk(
            disk_path,
            size_gb=requested_disk_gb,
        )

        self.attach_disk(
            name,
            disk_path,
            controller_name=controller_name,
            port=int(
                storage.get(
                    "disk_port",
                    0,
                )
            ),
        )

        self.set_boot_order(
            name,
            vbox.get(
                "boot_order",
                [
                    "disk",
                    "dvd",
                    "none",
                    "none",
                ],
            ),
        )

        if security.get(
            "secure_boot",
            False,
        ):
            self.configure_secure_boot(
                name
            )

        return disk_path

    # ------------------------------------------------------------------
    # Virtual disk handling
    # ------------------------------------------------------------------

    def default_disk_path(
        self,
        vm_name: str,
    ) -> Path:

        vm_directory = (
            self.vm_base_folder
            / vm_name
        )

        vm_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        return (
            vm_directory
            / f"{vm_name}.vdi"
        )

    def create_disk(
        self,
        path: str | Path,
        *,
        size_gb: int,
        fixed: bool = False,
    ) -> Path:

        target = Path(path).expanduser().resolve()

        if target.exists():
            raise VirtualBoxConfigurationError(
                f"Virtual disk already exists: {target}"
            )

        if size_gb <= 0:
            raise ValueError(
                "size_gb must be positive"
            )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        size_mb = size_gb * 1024

        self._run(
            [
                "createmedium",
                "disk",

                "--filename",
                str(target),

                "--size",
                str(size_mb),

                "--format",
                "VDI",

                "--variant",
                "Fixed" if fixed else "Standard",
            ]
        )

        return target

    # ------------------------------------------------------------------
    # Storage controllers
    # ------------------------------------------------------------------

    def _storage_controller_names(
        self,
        vm_name: str,
    ) -> set[str]:

        info = self.vm_info(vm_name)

        controllers: set[str] = set()

        for key, value in info.items():
            if key.startswith(
                "storagecontrollername"
            ):
                controllers.add(value)

        return controllers

    def ensure_sata_controller(
        self,
        vm_name: str,
        *,
        controller_name: str = DEFAULT_STORAGE_CONTROLLER,
        controller_type: str = DEFAULT_STORAGE_CONTROLLER_TYPE,
        port_count: int = 4,
    ) -> None:

        self.require_powered_off(vm_name)

        if (
            controller_name
            in self._storage_controller_names(
                vm_name
            )
        ):
            return

        self._run(
            [
                "storagectl",
                vm_name,

                "--name",
                controller_name,

                "--add",
                "sata",

                "--controller",
                controller_type,

                "--portcount",
                str(port_count),

                "--bootable",
                "on",
            ]
        )

    def attach_disk(
        self,
        vm_name: str,
        disk_path: str | Path,
        *,
        controller_name: str = DEFAULT_STORAGE_CONTROLLER,
        port: int = 0,
        device: int = 0,
    ) -> None:

        self.require_powered_off(vm_name)

        disk = Path(
            disk_path
        ).expanduser().resolve()

        if not disk.exists():
            raise FileNotFoundError(
                f"Virtual disk does not exist: {disk}"
            )

        self._run(
            [
                "storageattach",
                vm_name,

                "--storagectl",
                controller_name,

                "--port",
                str(port),

                "--device",
                str(device),

                "--type",
                "hdd",

                "--medium",
                str(disk),
            ]
        )

    # ------------------------------------------------------------------
    # ISO handling
    # ------------------------------------------------------------------

    def attach_iso(
        self,
        vm_name: str,
        iso_path: str | Path,
        *,
        controller_name: str = DEFAULT_STORAGE_CONTROLLER,
        port: int = 1,
        device: int = 0,
    ) -> None:

        self.require_powered_off(vm_name)

        iso = Path(
            iso_path
        ).expanduser().resolve()

        if not iso.exists():
            raise FileNotFoundError(
                f"ISO does not exist: {iso}"
            )

        if iso.suffix.lower() != ".iso":
            raise VirtualBoxConfigurationError(
                f"Expected .iso media: {iso}"
            )

        self._run(
            [
                "storageattach",
                vm_name,

                "--storagectl",
                controller_name,

                "--port",
                str(port),

                "--device",
                str(device),

                "--type",
                "dvddrive",

                "--medium",
                str(iso),
            ]
        )

    def attach_installation_media(
        self,
        vm_name: str,
        *,
        vendor_iso: str | Path,
        seed_iso: str | Path | None = None,
        guest_additions_iso: (
            str | Path | None
        ) = None,
        controller_name: str = (
            DEFAULT_STORAGE_CONTROLLER
        ),
        vendor_port: int = 1,
        seed_port: int = 2,
        guest_additions_port: int = 3,
    ) -> None:

        self.attach_iso(
            vm_name,
            vendor_iso,
            controller_name=controller_name,
            port=vendor_port,
        )

        if seed_iso is not None:
            self.attach_iso(
                vm_name,
                seed_iso,
                controller_name=controller_name,
                port=seed_port,
            )

        if guest_additions_iso is not None:
            self.attach_iso(
                vm_name,
                guest_additions_iso,
                controller_name=(
                    controller_name
                ),
                port=(
                    guest_additions_port
                ),
            )

    def detach_iso(
        self,
        vm_name: str,
        *,
        controller_name: str = DEFAULT_STORAGE_CONTROLLER,
        port: int = 1,
        device: int = 0,
    ) -> None:

        self.require_powered_off(vm_name)

        self._run(
            [
                "storageattach",
                vm_name,

                "--storagectl",
                controller_name,

                "--port",
                str(port),

                "--device",
                str(device),

                "--type",
                "dvddrive",

                "--medium",
                "none",
            ]
        )


    def default_guest_additions_iso(
        self,
    ) -> Path:
        """
        Return the Guest Additions ISO configured by the
        installed VirtualBox host.

        VBoxManage reports this through:

            VBoxManage list systemproperties
        """

        result = self._run(
            [
                "list",
                "systemproperties",
            ]
        )

        match = re.search(
            (
                r"^Default Guest Additions ISO:"
                r"\s*(?P<path>.*?)\s*$"
            ),
            result.stdout,
            flags=re.MULTILINE,
        )

        if not match:
            raise VirtualBoxConfigurationError(
                "VirtualBox did not report a "
                "Default Guest Additions ISO."
            )

        raw_path = (
            match.group("path")
            .strip()
        )

        if (
            not raw_path
            or raw_path.lower()
            in {
                "none",
                "<none>",
            }
        ):
            raise VirtualBoxConfigurationError(
                "VirtualBox has no default "
                "Guest Additions ISO configured."
            )

        iso_path = (
            Path(raw_path)
            .expanduser()
            .resolve()
        )

        if not iso_path.is_file():
            raise VirtualBoxConfigurationError(
                "VirtualBox reported a Guest "
                "Additions ISO that does not exist: "
                f"{iso_path}"
            )

        return iso_path


    # ------------------------------------------------------------------
    # Boot configuration
    # ------------------------------------------------------------------

    def set_boot_order(
        self,
        vm_name: str,
        order: Iterable[str],
    ) -> None:

        self.require_powered_off(vm_name)

        devices = list(order)

        if len(devices) > 4:
            raise VirtualBoxConfigurationError(
                "VirtualBox supports four boot-order slots."
            )

        valid = {
            "none",
            "floppy",
            "dvd",
            "disk",
            "net",
        }

        devices.extend(
            ["none"] * (4 - len(devices))
        )

        args = [
            "modifyvm",
            vm_name,
        ]

        for index, device in enumerate(
            devices,
            start=1,
        ):
            if device not in valid:
                raise VirtualBoxConfigurationError(
                    f"Invalid boot device: {device}"
                )

            args.extend(
                [
                    f"--boot{index}",
                    device,
                ]
            )

        self._run(args)

    # ------------------------------------------------------------------
    # Network interface handling
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_blocks(
        output: str,
    ) -> list[dict[str, str]]:

        blocks: list[dict[str, str]] = []
        current: dict[str, str] = {}

        for raw_line in output.splitlines():
            line = raw_line.rstrip()

            if not line.strip():
                if current:
                    blocks.append(current)
                    current = {}

                continue

            if ":" not in line:
                continue

            key, value = line.split(
                ":",
                1,
            )

            current[key.strip()] = (
                value.strip()
            )

        if current:
            blocks.append(current)

        return blocks

    def list_host_only_interfaces(
        self,
    ) -> list[HostOnlyInterface]:

        result = self._run(
            [
                "list",
                "hostonlyifs",
            ]
        )

        interfaces: list[
            HostOnlyInterface
        ] = []

        for block in self._parse_blocks(
            result.stdout
        ):
            name = block.get("Name")

            if not name:
                continue

            interfaces.append(
                HostOnlyInterface(
                    name=name,
                    ip_address=block.get(
                        "IPAddress"
                    ),
                    network_mask=block.get(
                        "NetworkMask"
                    ),
                    status=block.get(
                        "Status"
                    ),
                )
            )

        return interfaces

    def list_bridged_interface_names(
        self,
    ) -> list[str]:
        """
        Return host interfaces VirtualBox exposes for
        bridged networking.
        """

        result = self._run(
            [
                "list",
                "bridgedifs",
            ]
        )

        names: list[str] = []

        for block in self._parse_blocks(
            result.stdout
        ):
            name = str(
                block.get(
                    "Name",
                    "",
                )
            ).strip()

            if (
                name
                and
                name not in names
            ):
                names.append(
                    name
                )

        return names

    def ensure_management_interface(
        self,
        *,
        ip_address: str = MANAGEMENT_IP,
        netmask: str = MANAGEMENT_NETMASK,
    ) -> HostOnlyInterface:

        # Validate before touching VirtualBox.
        ipaddress.IPv4Address(ip_address)
        ipaddress.IPv4Address(netmask)

        interfaces = (
            self.list_host_only_interfaces()
        )

        requested_network = (
            ipaddress.IPv4Network(
                f"{ip_address}/{netmask}",
                strict=False,
            )
        )

        # First, return an already-correct
        # Crucible management interface.

        for interface in interfaces:
            if (
                interface.ip_address
                == ip_address
                and interface.network_mask
                == netmask
            ):
                self.disable_host_only_dhcp(
                    interface.name
                )

                return interface

        # Migrate Crucible's old v0.1 management
        # interface instead of creating an overlapping
        # /16 host-only network.

        for interface in interfaces:
            if (
                interface.ip_address
                == self.LEGACY_MANAGEMENT_IP
                and interface.network_mask
                == self.LEGACY_MANAGEMENT_NETMASK
            ):
                self._run(
                    [
                        "hostonlyif",
                        "ipconfig",
                        interface.name,

                        "--ip",
                        ip_address,

                        "--netmask",
                        netmask,
                    ]
                )

                self.disable_host_only_dhcp(
                    interface.name
                )

                return HostOnlyInterface(
                    name=interface.name,
                    ip_address=ip_address,
                    network_mask=netmask,
                    status=interface.status,
                )

        # Refuse to create a new interface if another
        # VirtualBox host-only network already overlaps
        # the Crucible management /16.

        for interface in interfaces:
            if (
                not interface.ip_address
                or not interface.network_mask
            ):
                continue

            try:
                existing_network = (
                    ipaddress.IPv4Network(
                        (
                            f"{interface.ip_address}/"
                            f"{interface.network_mask}"
                        ),
                        strict=False,
                    )
                )
            except ValueError:
                continue

            if existing_network.overlaps(
                requested_network
            ):
                raise VirtualBoxConfigurationError(
                    "Existing VirtualBox host-only "
                    f"interface '{interface.name}' "
                    f"uses overlapping network "
                    f"{existing_network}. "
                    "Crucible management requires "
                    f"{requested_network}."
                )

        before = {
            interface.name
            for interface
            in self.list_host_only_interfaces()
        }

        result = self._run(
            [
                "hostonlyif",
                "create",
            ]
        )

        # Most VirtualBox releases print:
        #
        # Interface 'vboxnet0' was successfully created
        #
        match = re.search(
            r"Interface\s+'([^']+)'",
            result.stdout
            + "\n"
            + result.stderr,
        )

        if match:
            interface_name = match.group(1)

        else:
            after = {
                interface.name
                for interface
                in self.list_host_only_interfaces()
            }

            new_interfaces = after - before

            if len(new_interfaces) != 1:
                raise VirtualBoxError(
                    "Could not determine the newly-created "
                    "host-only interface."
                )

            interface_name = (
                new_interfaces.pop()
            )

        self._run(
            [
                "hostonlyif",
                "ipconfig",
                interface_name,

                "--ip",
                ip_address,

                "--netmask",
                netmask,
            ]
        )

        self.disable_host_only_dhcp(
            interface_name
        )

        return HostOnlyInterface(
            name=interface_name,
            ip_address=ip_address,
            network_mask=netmask,
            status="Up",
        )

    def disable_host_only_dhcp(
        self,
        interface_name: str,
    ) -> None:

        result = self._run(
            [
                "list",
                "dhcpservers",
            ],
            check=False,
        )

        if result.returncode != 0:
            return

        blocks = self._parse_blocks(
            result.stdout
        )

        for block in blocks:
            interface = (
                block.get("Interface")
                or block.get("NetworkName")
            )

            if interface != interface_name:
                continue

            self._run(
                [
                    "dhcpserver",
                    "modify",

                    "--interface",
                    interface_name,

                    "--disable",
                ],
                check=False,
            )

    def configure_nic(
        self,
        vm_name: str,
        *,
        slot: int,
        mode: str,
        network: str | None = None,
        adapter: str | None = None,
        nic_type: str = "82540EM",
        mac_address: str | None = None,
        promiscuous_mode: str = "deny",
    ) -> None:

        self.require_powered_off(vm_name)

        if slot < 1 or slot > 8:
            raise VirtualBoxConfigurationError(
                "NIC slot must be between 1 and 8."
            )

        allowed_modes = {
            "none",
            "nat",
            "bridged",
            "intnet",
            "hostonly",
            "natnetwork",
        }

        if mode not in allowed_modes:
            raise VirtualBoxConfigurationError(
                f"Unsupported VirtualBox NIC mode: {mode}"
            )

        args = [
            "modifyvm",
            vm_name,

            f"--nic{slot}",
            mode,

            f"--nictype{slot}",
            nic_type,

            f"--cableconnected{slot}",
            "on",

            f"--nicpromisc{slot}",
            promiscuous_mode,
        ]

        if mode == "bridged":
            if not adapter:
                raise VirtualBoxConfigurationError(
                    "Bridged networking requires "
                    "adapter=<host interface>."
                )

            args.extend(
                [
                    f"--bridgeadapter{slot}",
                    adapter,
                ]
            )

        elif mode == "intnet":
            if not network:
                raise VirtualBoxConfigurationError(
                    "Internal networking requires "
                    "network=<name>."
                )

            args.extend(
                [
                    f"--intnet{slot}",
                    network,
                ]
            )

        elif mode == "hostonly":
            if not adapter:
                raise VirtualBoxConfigurationError(
                    "Host-only networking requires "
                    "adapter=<vboxnet interface>."
                )

            args.extend(
                [
                    f"--hostonlyadapter{slot}",
                    adapter,
                ]
            )

        elif mode == "natnetwork":
            if not network:
                raise VirtualBoxConfigurationError(
                    "NAT network mode requires "
                    "network=<name>."
                )

            args.extend(
                [
                    f"--nat-network{slot}",
                    network,
                ]
            )

        if mac_address:
            normalized = (
                mac_address
                .replace(":", "")
                .replace("-", "")
                .upper()
            )

            if not re.fullmatch(
                r"[0-9A-F]{12}",
                normalized,
            ):
                raise VirtualBoxConfigurationError(
                    f"Invalid MAC address: {mac_address}"
                )

            args.extend(
                [
                    f"--macaddress{slot}",
                    normalized,
                ]
            )

        self._run(args)

    def configure_topology_nic(
        self,
        vm_name: str,
        *,
        slot: int,
        attachment_type: str,
        mac_address: str,
        network_name: str | None = None,
        host_adapter: str | None = None,
        nic_type: str = "82540EM",
    ) -> None:
        """
        Configure one persistent user topology NIC.

        Crucible NAT and management adapters are not handled
        here; this method is for topology interfaces only.
        """

        attachment_type = (
            attachment_type
            .strip()
            .lower()
        )

        if attachment_type == "intnet":
            if not network_name:
                raise VirtualBoxConfigurationError(
                    "Internal topology NIC "
                    "requires network_name."
                )

            self.configure_nic(
                vm_name,
                slot=slot,
                mode="intnet",
                network=network_name,
                nic_type=nic_type,
                mac_address=mac_address,
            )

            return

        if attachment_type == "bridged":
            if not host_adapter:
                raise VirtualBoxConfigurationError(
                    "Bridged topology NIC "
                    "requires host_adapter."
                )

            self.configure_nic(
                vm_name,
                slot=slot,
                mode="bridged",
                adapter=host_adapter,
                nic_type=nic_type,
                mac_address=mac_address,
            )

            return

        raise VirtualBoxConfigurationError(
            "Unsupported topology NIC type: "
            f"{attachment_type}"
        )

    def configure_internal_nic(
        self,
        vm_name: str,
        *,
        slot: int,
        network_name: str,
        nic_type: str = "82540EM",
        promiscuous_mode: str = "deny",
    ) -> None:

        # VirtualBox internal networks do not require an
        # explicit "create network" operation. They come into
        # existence when VMs attach to the same named intnet.

        self.configure_nic(
            vm_name,
            slot=slot,
            mode="intnet",
            network=network_name,
            nic_type=nic_type,
            promiscuous_mode=promiscuous_mode,
        )

    def configure_nat_nic(
        self,
        name: str,
        *,
        slot: int,
        mac_address: str | None = None,
        nic_type: str = "82540EM",
    ) -> None:
        """
        Configure Crucible's temporary NAT/Internet NIC.

        Slot assignment is resolved by the orchestration layer;
        the provider must not assume that NAT is NIC 1.
        """

        self.configure_nic(
            name,
            slot=slot,
            mode="nat",
            nic_type=nic_type,
            mac_address=mac_address,
        )


    def configure_management_nic(
        self,
        vm_name: str,
        *,
        slot: int,
        nic_type: str = "82540EM",
        mac_address: str | None = None,
    ) -> HostOnlyInterface:

        interface = (
            self.ensure_management_interface()
        )

        self.configure_nic(
            vm_name,
            slot=slot,
            mode="hostonly",
            adapter=interface.name,
            nic_type=nic_type,
            mac_address=mac_address,
        )

        return interface

    def disable_nic(
        self,
        vm_name: str,
        *,
        slot: int,
    ) -> None:

        self.require_powered_off(vm_name)

        self._run(
            [
                "modifyvm",
                vm_name,
                f"--nic{slot}",
                "none",
            ]
        )

    def set_nat_localhost_reachable(
        self,
        vm_name: str,
        *,
        slot: int,
        enabled: bool = True,
    ) -> None:
        """
        Allow a NAT-connected guest to access services
        bound to the host's loopback interface.

        With VirtualBox's default NAT network, the host
        loopback is exposed to the guest as 10.0.2.2.

        Kali's unattended installer uses this to fetch
        Crucible's temporary preseed.cfg.
        """

        self.require_powered_off(
            vm_name
        )

        if slot < 1 or slot > 8:
            raise VirtualBoxConfigurationError(
                "NIC slot must be between 1 and 8."
            )

        self._run(
            [
                "modifyvm",
                vm_name,

                f"--nat-localhostreachable{slot}",

                (
                    "on"
                    if enabled
                    else "off"
                ),
            ]
        )

    # ------------------------------------------------------------------
    # TPM / Secure Boot
    # ------------------------------------------------------------------

    def configure_secure_boot(
        self,
        vm_name: str,
    ) -> None:

        """
        Initializes the EFI variable store and enables Secure Boot
        using VirtualBox's built-in Microsoft / Oracle certificates.

        This should normally only be performed on a newly-created VM.
        """

        self.require_powered_off(vm_name)

        if not self.version().at_least(
            7,
            1,
        ):
            raise VirtualBoxConfigurationError(
                "This Crucible Secure Boot path requires "
                "a modern VirtualBox 7.x installation."
            )

        # Reset/create the EFI variable store.
        self._run(
            [
                "modifynvram",
                vm_name,
                "inituefivarstore",
            ]
        )

        # Microsoft KEK / DB certificates used by Windows.
        self._run(
            [
                "modifynvram",
                vm_name,
                "enrollmssignatures",
            ]
        )

        # Platform key supplied by VirtualBox.
        self._run(
            [
                "modifynvram",
                vm_name,
                "enrollorclpk",
            ]
        )

        self._run(
            [
                "modifynvram",
                vm_name,
                "secureboot",
                "--enable",
            ]
        )

    # ------------------------------------------------------------------
    # VM power management
    # ------------------------------------------------------------------

    def start_vm(
        self,
        name: str,
        *,
        headless: bool = True,
    ) -> None:

        self.require_vm(name)

        state = self.vm_state(name)

        if state == "running":
            return

        if state == "saved":
            # Starting a saved VM is valid.
            pass

        elif state not in {
            "poweroff",
            "aborted",
            "saved",
        }:
            raise VMStateError(
                f"Cannot start '{name}' from state '{state}'."
            )

        self._run(
            [
                "startvm",
                name,
                "--type",
                "headless" if headless else "gui",
            ]
        )

    def acpi_shutdown(
        self,
        name: str,
    ) -> None:

        self.require_vm(name)

        if not self.is_running(name):
            return

        self._run(
            [
                "controlvm",
                name,
                "acpipowerbutton",
            ]
        )

    def poweroff(
        self,
        name: str,
    ) -> None:

        self.require_vm(name)

        if not self.is_running(name):
            return

        self._run(
            [
                "controlvm",
                name,
                "poweroff",
            ]
        )

    def wait_for_poweroff(
        self,
        name: str,
        *,
        timeout: int = 120,
        poll_interval: float = 2.0,
    ) -> bool:

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            state = self.vm_state(name)

            if state in {
                "poweroff",
                "aborted",
            }:
                return True

            time.sleep(poll_interval)

        return False

    def shutdown_gracefully(
        self,
        name: str,
        *,
        timeout: int = 120,
        force_after_timeout: bool = False,
    ) -> None:

        if not self.is_running(name):
            return

        self.acpi_shutdown(name)

        if self.wait_for_poweroff(
            name,
            timeout=timeout,
        ):
            return

        if force_after_timeout:
            self.poweroff(name)
            return

        raise VMStateError(
            f"VM '{name}' did not shut down within "
            f"{timeout} seconds."
        )

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def take_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
        *,
        description: str | None = None,
    ) -> None:

        self.require_vm(vm_name)

        args = [
            "snapshot",
            vm_name,
            "take",
            snapshot_name,
        ]

        if description:
            args.extend(
                [
                    "--description",
                    description,
                ]
            )

        self._run(args)

    def restore_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
    ) -> None:

        self.require_vm(vm_name)

        if self.is_running(vm_name):
            raise VMStateError(
                "Stop the VM before restoring a snapshot."
            )

        self._run(
            [
                "snapshot",
                vm_name,
                "restore",
                snapshot_name,
            ]
        )

    def delete_snapshot(
        self,
        vm_name: str,
        snapshot_name: str,
    ) -> None:

        self.require_vm(vm_name)

        self._run(
            [
                "snapshot",
                vm_name,
                "delete",
                snapshot_name,
            ]
        )

    # ------------------------------------------------------------------
    # VM deletion
    # ------------------------------------------------------------------

    def delete_vm(
        self,
        name: str,
        *,
        force: bool = False,
    ) -> None:

        if not self.vm_exists(name):
            return

        if self.is_running(name):
            if not force:
                raise VMStateError(
                    f"VM '{name}' is running. "
                    "Use force=True to power it off."
                )

            self.poweroff(name)

        self._run(
            [
                "unregistervm",
                name,
                "--delete",
            ]
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnostics(self) -> dict[str, Any]:

        version = self.version()

        return {
            "provider": "virtualbox",
            "available": self.available(),
            "binary": self.binary,
            "version": version.raw,
            "version_major": version.major,
            "version_minor": version.minor,
            "version_patch": version.patch,
            "vm_base_folder": str(
                self.vm_base_folder
            ),
            "registered_vms": [
                {
                    "name": vm.name,
                    "uuid": vm.uuid,
                }
                for vm in self.list_vms()
            ],
            "host_only_interfaces": [
                {
                    "name": interface.name,
                    "ip_address": interface.ip_address,
                    "network_mask": interface.network_mask,
                    "status": interface.status,
                }
                for interface
                in self.list_host_only_interfaces()
            ],
        }

# ---------------------------------------------------------------------------
# Development smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    provider = VirtualBoxProvider(
        verbose=True
    )

    info = provider.diagnostics()

    print()
    print("Operation Crucible - VirtualBox Provider")
    print("=" * 50)
    print(f"VBoxManage: {info['binary']}")
    print(f"Version:    {info['version']}")
    print(f"VM folder:  {info['vm_base_folder']}")
    print(
        f"VMs:        "
        f"{len(info['registered_vms'])}"
    )
    print(
        f"Host-only:  "
        f"{len(info['host_only_interfaces'])}"
    )
