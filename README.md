# Operation Crucible

<p align="center">
  <strong>Forge disposable cybersecurity lab machines from installation media to Ansible-ready systems with minimal human input.</strong>
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-v0.1.4-blue">
  <img alt="Status" src="https://img.shields.io/badge/status-early%20alpha-yellow">
  <img alt="Hypervisor" src="https://img.shields.io/badge/hypervisor-VirtualBox-orange">
  <img alt="Automation" src="https://img.shields.io/badge/automation-Ansible-red">
  <img alt="Language" src="https://img.shields.io/badge/language-Python-3776AB">
</p>

> **Current release:** `v0.1.4`  
> **Current end-to-end guest support:** Ubuntu Server 26.04, Ubuntu Desktop 26.04, and Kali Linux Rolling  
> **Next major milestone:** `v0.2` — Windows unattended provisioning and Ansible management

---

## What is Operation Crucible?

Operation Crucible is a local virtual-lab automation framework built around a simple idea: repetitive infrastructure work should be automated so that the valuable part of a lab can receive the human attention.

The project began from what one of my professors described as the difference between being **"dumb lazy"** and **"smart lazy."** Manually rebuilding the same virtual machines, networks, users, SSH configuration, package state, and management plumbing for every cybersecurity assignment is repetitive work. Crucible exists to automate that repetition while leaving the actual learning, troubleshooting, security configuration, and experimentation to the student.

The immediate goal is to reduce the setup phase of a lab from hours of clicking through installers and configuring machines into a short interactive workflow. A user tells Crucible what kind of machine is required, accepts or adjusts the hardware and installation defaults, and the Forge handles the rest.

At the end of a successful Linux forge, Crucible has gone from a normal vendor installation ISO to:

```text
installation ISO
      ↓
VirtualBox VM creation
      ↓
virtual hardware + networking
      ↓
zero-touch operating-system installation
      ↓
Crucible management network
      ↓
SSH
      ↓
first-boot bootstrap
      ↓
Ansible inventory
      ↓
ansible.builtin.ping
      ↓
pong
```

The project is still early-alpha software, but the core Linux forging pipeline is now functional.

---

## Current Capabilities

### Supported end-to-end guests

| Operating system | Installer backend | Forge status | Final management |
|---|---|---:|---|
| Ubuntu Server 26.04 | Subiquity / NoCloud autoinstall | ✅ Working | SSH + Ansible |
| Ubuntu Desktop 26.04 | Subiquity / NoCloud autoinstall | ✅ Working | SSH + Ansible |
| Kali Linux Rolling | Debian Installer preseed | ✅ Working | SSH + Ansible |
| Windows 10 | Windows unattended backend planned | 🚧 Not yet forgeable | WinRM + Ansible planned |
| Windows 11 | Windows unattended backend planned | 🚧 Not yet forgeable | WinRM + Ansible planned |
| Windows Server 2022 | Windows unattended backend planned | 🚧 Not yet forgeable | WinRM + Ansible planned |

### The Forge currently handles

- Interactive OS selection.
- Automatic or custom VirtualBox VM naming.
- Collision detection against existing VirtualBox/Crucible machine names.
- OS-profile-driven hardware defaults.
- Custom CPU count.
- Custom memory allocation.
- Custom virtual disk size.
- EFI or BIOS selection where supported.
- Virtual graphics controller selection.
- Configurable VRAM.
- Optional 3D acceleration.
- Optional additional VirtualBox internal networks.
- Automatic VirtualBox VM and VDI creation.
- Installation ISO discovery and classification.
- Ubuntu Server unattended installation.
- Ubuntu Desktop unattended installation.
- Kali Rolling unattended installation.
- Generated Linux login credentials.
- Optional automatic inclusion of a detected local SSH public key.
- Automatic host-only Crucible management networking.
- Persistent management IP allocation.
- Temporary NAT Internet access during provisioning.
- Shared Linux first-boot bootstrap logic.
- OpenSSH installation and enablement.
- Python installation for Ansible.
- Runtime Ansible inventory generation.
- Automatic waiting for SSH availability.
- Automatic waiting for the Crucible bootstrap marker.
- Final Ansible connectivity verification.

A successful forge ends with output similar to:

```text
Management target: crucible@172.31.0.2

[✓] SSH port is reachable.
[✓] Bootstrap complete.

Verifying Ansible connectivity...

kali-01 | SUCCESS => {
    "changed": false,
    "ping": "pong"
}

[✓] Ansible connectivity verified.

==========================================
          FORGE COMPLETE
==========================================
```

---

# Architecture

Operation Crucible intentionally separates operating-system provisioning from hypervisor control and runtime management.

A simplified view of the project is:

```text
crucible.py
   │
   ├── interactive Forge workflow
   ├── machine/lab manifest generation
   ├── management IP allocation
   └── final SSH/bootstrap/Ansible verification
            │
            ↓
crucible/cli/create_machine.py
   │
   ├── loads OS profile
   ├── resolves installation media
   ├── chooses installer backend
   ├── creates VM
   └── starts unattended installation
            │
      ┌─────┴──────────────┐
      ↓                    ↓
Ubuntu backend         Kali backend
NoCloud CIDATA         Debian preseed
      │                    │
      └────────┬───────────┘
               ↓
crucible/hypervisors/virtualbox.py
               │
               ↓
          VirtualBox
               │
               ↓
        installed guest
               │
               ↓
      common Linux bootstrap
               │
               ↓
           SSH + Ansible
```

### Important directories

```text
operation-crucible/
├── crucible.py
├── crucible/
│   ├── cli/
│   │   └── create_machine.py
│   ├── hypervisors/
│   │   └── virtualbox.py
│   ├── networking/
│   │   └── management.py
│   ├── provisioning/
│   │   ├── image_detector.py
│   │   ├── ubuntu_autoinstall.py
│   │   ├── kali_preseed.py
│   │   └── preseed_server.py
│   └── validation/
├── profiles/
│   └── os/
├── installers/
│   └── linux/
├── config/
│   └── images.yml
├── images/
│   └── iso/
└── .crucible/              # generated locally at runtime
```

### Runtime state

Crucible stores generated state under:

```text
.crucible/
```

This includes generated manifests, Ansible inventory, IPAM state, generated preseed/autoinstall content, and VM/runtime data.

The directory is intentionally ignored by Git.

Large VM media and disk formats are also ignored, including `.iso`, `.vdi`, `.vmdk`, `.qcow2`, `.ova`, and `.ovf` files.

---

# Networking Model

Every currently supported Linux forge receives at least two virtual NICs.

## NIC 1 — Provisioning / Internet

```text
VirtualBox NIC 1
      ↓
NAT
      ↓
Internet access
```

This interface is used for installation-time package access and general outbound connectivity.

On Kali, predictable interface naming is disabled for the provisioning path so that:

```text
eth0 = NIC 1 = NAT
```

Kali also temporarily reaches Crucible's local preseed HTTP service through VirtualBox NAT at `10.0.2.2`.

## NIC 2 — Crucible Management

```text
VirtualBox NIC 2
      ↓
Host-only interface
      ↓
172.31.0.0/16
```

Crucible reserves:

```text
Controller: 172.31.0.1
Guests:     172.31.0.2 onward
```

Management addresses are persistently allocated by Crucible's IPAM state.

For Kali:

```text
eth1 = NIC 2 = Crucible management
```

The management interface does not become the guest's default Internet route.

## NIC 3+

Additional NICs can be attached to user-defined VirtualBox internal networks. These are intended for future multi-machine lab topologies, isolated security exercises, routing labs, simulated enterprise networks, and similar coursework.

---

# How Linux Provisioning Works

## Ubuntu

Ubuntu Server and Ubuntu Desktop use Subiquity autoinstall with generated NoCloud data.

Crucible:

1. Renders the unattended installation data.
2. Creates a small `CIDATA` seed ISO.
3. Attaches the vendor Ubuntu ISO and seed ISO.
4. Boots the VM.
5. Uses VirtualBox keyboard injection to add the required autoinstall boot argument.
6. Allows Ubuntu to install without user interaction.
7. Runs the shared Crucible Linux bootstrap.
8. Reboots into the installed system.
9. Waits for SSH and verifies Ansible connectivity.

Ubuntu Server and Desktop have separate GRUB edit behavior because their installer boot entries differ.

## Kali

Kali uses Debian Installer preseeding rather than Ubuntu's NoCloud mechanism.

Crucible:

1. Renders `preseed.cfg`.
2. Starts a temporary HTTP server bound to the controller's loopback interface.
3. Allows the Kali guest to reach that service through VirtualBox NAT.
4. Edits the Kali UEFI GRUB installer entry using VirtualBox keyboard injection.
5. Supplies the preseed URL to Debian Installer.
6. Creates persistent NetworkManager profiles for NAT and management networking.
7. Installs and enables SSH.
8. Installs a one-shot first-boot Crucible bootstrap service.
9. Reboots into the installed Kali system.
10. Runs the heavy bootstrap from the real installed OS rather than from the installer chroot.
11. Creates the bootstrap-complete marker.
12. Allows Forge to continue into Ansible verification.

---

# Requirements

Operation Crucible is currently designed around a **Linux controller**, with Ubuntu being the primary development and test environment.

## Hardware

Recommended:

- x86-64 processor.
- Intel VT-x or AMD-V enabled in firmware.
- At least 16 GB host RAM for comfortable lab use.
- Sufficient free storage for installation ISOs and VM disks.
- At least 2 CPU threads available per basic guest.
- Internet access during initial guest provisioning unless your environment provides local mirrors.

Actual guest hardware can be changed from the Forge prompts.

## Controller software

Required:

- Python 3
- VirtualBox with `VBoxManage` available in `PATH`
- Ansible / `ansible` command
- PyYAML
- Jinja2
- OpenSSL
- OpenSSH client
- An ISO creation utility for Ubuntu seed media (`xorriso` recommended)

A modern VirtualBox 7.x installation is recommended.

---

# Installation

## 1. Install host dependencies

On an Ubuntu controller, start with:

```bash
sudo apt update

sudo apt install -y \
    python3 \
    python3-venv \
    python3-pip \
    openssl \
    openssh-client \
    xorriso
```

Install VirtualBox using the package appropriate for your Ubuntu release or Oracle's supported VirtualBox packages.

If your Ubuntu repositories provide the desired VirtualBox version, this may be as simple as:

```bash
sudo apt install virtualbox
```

Verify that the command-line interface is available:

```bash
VBoxManage --version
```

Do not continue until this returns a VirtualBox version rather than `command not found`.

---

## 2. Clone Operation Crucible

```bash
git clone https://github.com/omerrimen-home/operation-crucible.git
cd operation-crucible
```

The repository's default branch is:

```text
main
```

---

## 3. Create a Python virtual environment

Recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Upgrade pip:

```bash
python3 -m pip install --upgrade pip
```

Install the Python dependencies currently used by Crucible:

```bash
python3 -m pip install \
    PyYAML \
    Jinja2 \
    ansible-core
```

Verify Ansible:

```bash
ansible --version
```

Because Forge checks for the `ansible` executable in the current environment, keep the virtual environment activated while running Crucible if Ansible was installed into the venv.

---

## 4. Verify the controller

Run:

```bash
python3 --version
VBoxManage --version
ansible --version
openssl version
xorriso -version
```

All should return successfully.

You can also compile the project as a quick Python syntax check:

```bash
python3 -m compileall \
    crucible.py \
    crucible
```

---

# Installation Media

Large vendor ISOs are intentionally **not** stored in this repository.

Place your installation media in:

```text
images/iso/
```

For current Linux usage, you only need the ISO for the operating system you intend to forge.

## Ubuntu Server 26.04

Use the AMD64 Ubuntu Server 26.04 installation ISO.

Typical filename:

```text
ubuntu-26.04-live-server-amd64.iso
```

Point releases such as `26.04.1` are also expected by the image detector.

Official source:

https://ubuntu.com/download/server

## Ubuntu Desktop 26.04

Use the AMD64 Ubuntu Desktop 26.04 ISO.

Typical filename:

```text
ubuntu-26.04-desktop-amd64.iso
```

Official source:

https://ubuntu.com/download/desktop

## Kali Linux Rolling

Use the standard **Kali Installer AMD64** image.

Do **not** use the Live image for the current Crucible Kali backend.

A current stable filename looks like:

```text
kali-linux-2026.2-installer-amd64.iso
```

Official source:

https://www.kali.org/get-kali/#kali-installer-images

---

## Check image discovery

Optional but useful:

```bash
python3 -m \
    crucible.provisioning.image_detector
```

or:

```bash
python3 -m \
    crucible.provisioning.image_detector \
    --json
```

The selected ISO should appear under the correct image ID, for example:

```text
ubuntu-26.04-server
ubuntu-26.04-desktop
kali-rolling
```

### Note about the current image inventory

`config/images.yml` already contains definitions for the planned Windows targets. Depending on which ISOs you have placed in `images/iso/`, the standalone inventory validator may therefore report other configured images as missing.

For the current Forge, the important requirement is that the ISO for the operating system you select is recognized and uniquely resolvable.

---

# Running Operation Crucible

From the repository root, with your Python environment active:

```bash
python3 crucible.py
```

The entry point also has a Python shebang, so you may optionally make it executable:

```bash
chmod +x crucible.py
./crucible.py
```

**Do not normally run Crucible with `sudo`.**

VirtualBox stores per-user VM configuration, Crucible detects SSH keys from the current user, and the Forge is designed to run as the normal desktop/controller account.

---

# The Forge Workflow

When launched, Crucible guides you through the machine definition.

The current workflow asks for:

1. Number of VMs.
2. Operating system.
3. VirtualBox VM name.
4. VM hardware settings.
5. Unattended-install configuration.
6. Login identity.
7. SSH behavior.

At present, one VM per Forge invocation is supported.

## Default login

The default guest user is:

```text
crucible
```

Crucible can generate a strong random password.

The plaintext password is shown in the terminal so that you can log into the guest if required, but the plaintext password is not written into the generated machine manifest. A password hash is used for unattended installation.

If Crucible detects a suitable local SSH public key, the defaults can include it automatically.

---

# Example First Run

Start:

```bash
./crucible.py
```

Choose one of the currently supported operating systems:

```text
1. Ubuntu Server 26.04
2. Ubuntu Desktop 26.04
3. Kali Linux Rolling
```

For a first test, accepting the defaults is recommended.

Crucible will then:

```text
generate manifests
      ↓
allocate management IP
      ↓
identify installation ISO
      ↓
create VirtualBox VM
      ↓
create virtual disk
      ↓
configure NICs
      ↓
generate unattended installer data
      ↓
boot installer
      ↓
complete installation
      ↓
bootstrap installed OS
      ↓
wait for SSH
      ↓
generate Ansible inventory
      ↓
run Ansible ping
```

No interaction with the guest installer should be required.

---

# Generated Files and State

The following are created locally as Crucible runs:

```text
.crucible/
├── ansible/
│   └── inventory.yml
├── generated/
├── manifests/
│   ├── labs/
│   └── machines/
├── state/
│   └── management-ipam.yml
└── vms/
```

These are runtime artifacts rather than source code and are intentionally ignored by Git.

Ubuntu seed ISOs may also be produced under:

```text
images/generated/
```

Large source installation media remains local.

---

# Manually Verifying a Forged Machine

## Management IP

Inspect:

```bash
cat .crucible/state/management-ipam.yml
```

or the generated machine manifest:

```bash
ls .crucible/manifests/machines/
```

## Ping

From the controller:

```bash
ping -c 3 172.31.0.X
```

## SSH port

```bash
nc -vz 172.31.0.X 22
```

## SSH login

```bash
ssh crucible@172.31.0.X
```

## Ansible

Inspect the runtime inventory:

```bash
cat .crucible/ansible/inventory.yml
```

Then:

```bash
ansible <vm-name> \
    -i .crucible/ansible/inventory.yml \
    -m ansible.builtin.ping
```

Expected:

```text
<vm-name> | SUCCESS => {
    "changed": false,
    "ping": "pong"
}
```

---

# Troubleshooting

## `VBoxManage` is not found

Check:

```bash
which VBoxManage
VBoxManage --version
```

Install or repair VirtualBox before running Crucible.

---

## ISO is not recognized

List the directory:

```bash
ls -lh images/iso/
```

Run:

```bash
python3 -m \
    crucible.provisioning.image_detector \
    --json
```

Check:

- filename,
- `image_id`,
- `media_type`,
- whether more than one ISO matched the same image ID.

Use the standard vendor filenames whenever possible.

---

## Forge is waiting for SSH

First confirm the guest has its management address.

Inside Linux:

```bash
ip -br addr
```

For Kali:

```bash
nmcli device status
nmcli connection show
```

Check SSH:

```bash
systemctl status ssh.service
sudo ss -lntp | grep ':22'
```

---

## Forge reaches SSH but waits for bootstrap

On the guest:

```bash
ls -l /var/lib/crucible/
```

A completed bootstrap should create:

```text
bootstrap-complete
```

Kali also uses a first-boot service:

```bash
systemctl status \
    crucible-bootstrap.service
```

Inspect its journal:

```bash
sudo journalctl \
    -u crucible-bootstrap.service \
    --no-pager
```

The shared Linux bootstrap log is:

```bash
sudo cat /var/log/crucible-bootstrap.log
```

---

## Management IP conflicts with another network

Crucible currently reserves:

```text
172.31.0.0/16
```

with:

```text
172.31.0.1
```

assigned to the controller-side host-only interface.

If your VPN, employer network, home lab, or another local route already uses this range, routing conflicts are possible.

The management network is currently defined in:

```text
crucible/networking/management.py
```

---

# Current Limitations

Operation Crucible is still under active development.

Current limitations include:

- VirtualBox is the only implemented hypervisor.
- The Linux controller path is the primary supported environment.
- Only one VM is forged per interactive run.
- Do not run multiple Forge processes concurrently; current runtime inventory and IPAM state are shared.
- Ubuntu Server, Ubuntu Desktop, and Kali are the only end-to-end guest implementations.
- Windows image definitions exist, but Windows provisioning is not yet exposed as a completed Forge target.
- macOS is not supported.
- ISO detection relies on configured filename/metadata patterns.
- The CLI, manifests, profiles, and internal APIs may change rapidly during the `0.x` series.
- Cleanup/recovery tooling for interrupted Forge runs is still limited.
- The default Linux workflow permits SSH password authentication for convenience in lab environments.
- The project is intended for controlled lab and coursework environments rather than production infrastructure.

---

# Security Notes

Crucible intentionally trades some production-hardening choices for repeatable lab usability.

Current behavior includes:

- generated login passwords,
- SSH password authentication enabled by default,
- optional SSH public-key injection,
- local host-only management networking,
- local runtime state,
- ignored secret/key patterns in `.gitignore`,
- ignored VM disks and installation media.

Do not assume the generated guest configuration is production-hardened.

If you use Crucible outside an isolated personal lab, review:

- SSH authentication policy,
- host-only network exposure,
- guest firewall rules,
- generated credentials,
- retained runtime manifests,
- package update behavior.

---

# Version History

The `0.1.x` series establishes the Linux Forge foundation. Each tagged release has progressively removed another category of manual VM setup.

## v0.1 — August 19, 2026

**Milestone: first complete zero-touch Ubuntu Server forge**

Tag:

```text
v0.1
```

The first major proof of concept established the complete objective of the project:

```text
fresh Linux VM
      ↓
unattended installation
      ↓
SSH/bootstrap
      ↓
Ansible
      ↓
ping = pong
```

Major accomplishments:

- Ubuntu Server unattended installation.
- VirtualBox VM creation controlled from Python.
- Automated disk/media attachment.
- Automated network construction.
- Linux bootstrap integration.
- SSH management.
- Runtime Ansible inventory generation.
- Automatic `ansible.builtin.ping` verification.
- First end-to-end Forge workflow requiring no guest-side interaction.

This release proved that the central concept of Operation Crucible was viable.

---

## v0.1.1 — August 20, 2026

**Milestone: hardware customization**

Tag:

```text
v0.1.1
```

The Forge moved beyond a single hard-coded VM shape.

Added:

- OS-profile-driven hardware defaults.
- Custom CPU count.
- Custom RAM.
- Custom virtual disk size.
- VRAM configuration.
- EFI/BIOS selection.
- VirtualBox graphics-controller selection.
- Optional 3D acceleration.
- Additional VirtualBox internal-network NICs.
- Hardware validation before VM creation.

This version turned the VM definition into a reusable framework rather than a single Ubuntu proof of concept.

---

## v0.1.2 — August 20, 2026

**Milestone: second operating system / Ubuntu Desktop**

Tag:

```text
v0.1.2
```

Added full Ubuntu Desktop 26.04 support alongside Ubuntu Server.

Major changes:

- Ubuntu Desktop 26.04 profile.
- Ubuntu Desktop installation-media recognition.
- Desktop-specific Subiquity source selection.
- Separate Ubuntu Server and Desktop boot automation.
- Flavor-aware VirtualBox GRUB editing.
- Continued convergence on one shared post-install Linux management path.

After this release, Crucible could forge two distinct guest operating-system variants from the same interactive framework.

---

## v0.1.3 — August 20, 2026

**Milestone: dynamic machine identity and management IPAM**

Tag:

```text
v0.1.3
```

Added:

- Automatic numbered VM names such as:

  ```text
  ubuntu-server-01
  ubuntu-server-02
  ```

- User-defined VM names.
- Name validation.
- Detection of existing VirtualBox/Crucible machine names.
- Dynamic management IP allocation.
- Persistent IP leases.
- Dedicated `172.31.0.0/16` Crucible management network.
- Controller management address `172.31.0.1`.
- Guest allocation beginning at `172.31.0.2`.
- Migration logic for the older Crucible management-network layout.

This release removed two important remaining hard-coded assumptions: machine names and management addresses.

---

## v0.1.4 — August 20, 2026

**Milestone: Kali Linux Rolling capability**

Tag:

```text
v0.1.4
```

Added Kali Rolling as the third complete Forge target.

Major capabilities:

- Kali Rolling OS profile.
- Kali installer-media recognition.
- Debian Installer preseed generation.
- Temporary local HTTP preseed service.
- VirtualBox NAT access to the controller's loopback service.
- Automated Kali UEFI GRUB editing.
- Non-interactive Debian Installer boot arguments.
- Persistent NetworkManager profiles for:
  - NAT/Internet networking,
  - Crucible management networking.
- Shared Linux bootstrap installation.
- Kali first-boot systemd bootstrap service.
- OpenSSH enablement.
- Final convergence with the same SSH and Ansible verification used by Ubuntu.

With this release, Crucible supports:

```text
Ubuntu Server 26.04
Ubuntu Desktop 26.04
Kali Linux Rolling
```

all through the same top-level Forge interface.

---

# Next Version

## v0.2 — Planned

**Milestone: Windows Forge capability**

The next major version is intended to extend the successful Linux pipeline to Windows.

The target outcome is:

```text
fresh Windows VM
      ↓
zero-touch Windows installation
      ↓
Windows management bootstrap
      ↓
WinRM
      ↓
Ansible
      ↓
ansible.windows.win_ping
      ↓
pong
```

Planned work includes:

- Windows unattended installation backend.
- `Autounattend.xml` generation.
- Windows-specific identity and installation configuration.
- Windows guest bootstrap through PowerShell.
- WinRM configuration.
- Ansible Windows inventory variables.
- `ansible.windows` collection integration.
- Final `ansible.windows.win_ping` verification.
- Windows network configuration on the existing Crucible management plane.
- Integration with the existing VirtualBox provider and hardware-profile system.

Image definitions already exist for:

- Windows 10,
- Windows 11,
- Windows Server 2022.

The exact order in which those Windows targets become fully forgeable may evolve during `v0.2` development.

---

# Longer-Term Direction

Operation Crucible is intended to grow beyond creating one machine at a time.

The broader direction includes:

- Multi-VM Forge runs.
- Reusable lab topology manifests.
- Router/firewall machines.
- Domain-controller and Active Directory labs.
- Automated DNS infrastructure.
- Linux and Windows enterprise-service roles.
- Multi-segment internal networks.
- Automatic course/lab-specific Ansible roles.
- Traffic generation.
- Security-tool deployment.
- Repeatable vulnerable and defensive environments.
- Snapshot/checkpoint automation.
- Hypervisor abstraction beyond VirtualBox.
- Faster teardown and rebuild workflows.
- A larger library of OS and lab profiles.

The long-term goal is not to automate away cybersecurity coursework. It is to automate the repetitive infrastructure setup so that more time can be spent on the systems, protocols, attacks, defenses, and troubleshooting that the lab is actually meant to teach.

---

# Development Status

Operation Crucible is currently an **early-alpha personal automation project**.

The repository is usable for experimentation, but users should expect rapid changes to:

- manifests,
- OS profiles,
- installer templates,
- runtime state,
- CLI prompts,
- internal Python APIs,
- networking behavior.

If you are experimenting with it, keep important work outside disposable Crucible VM disks and treat forged guests as rebuildable lab systems.

---

## Quick Start

For experienced users, the current setup can be summarized as:

```bash
git clone https://github.com/omerrimen-home/operation-crucible.git
cd operation-crucible

python3 -m venv .venv
source .venv/bin/activate

python3 -m pip install --upgrade pip
python3 -m pip install PyYAML Jinja2 ansible-core

# Install VirtualBox and xorriso separately.
VBoxManage --version

# Put the desired vendor ISO in:
# images/iso/

python3 -m compileall crucible.py crucible

./crucible.py
```

Then follow the Forge prompts.

If everything succeeds, the last word from the newly forged Linux machine should effectively be:

```text
pong
```
