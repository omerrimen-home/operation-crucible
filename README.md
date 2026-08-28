# Operation Crucible

**Current release: v0.2**  
**Status: early alpha**  
**Controller: Linux/Ubuntu**  
**Hypervisor: Oracle VirtualBox**  
**Topology limit: one VM per Forge invocation**

Operation Crucible is a local cybersecurity-lab automation framework that turns ordinary vendor installation media into disposable, Ansible-ready virtual machines with minimal human input.

A successful Forge run does not stop when the guest boots. Crucible waits until the new machine is reachable, its bootstrap has completed, and Ansible returns a final `pong`.

## Supported guests

| Operating system | Installer backend | Status | Management |
|---|---|---:|---|
| Ubuntu Server 26.04 | Subiquity / NoCloud | ✅ | SSH + Ansible |
| Ubuntu Desktop 26.04 | Subiquity / NoCloud | ✅ | SSH + Ansible |
| Kali Linux Rolling | Debian Installer preseed | ✅ | SSH + Ansible |
| Windows 10 Pro | Windows Unattend | ✅ | WinRM HTTPS / PSRP + Ansible |
| Windows 11 Pro | Windows Unattend | ✅ | WinRM HTTPS / PSRP + Ansible |
| Windows Server 2022 | Windows Unattend | ✅ | WinRM HTTPS / PSRP + Ansible |

Windows Server 2022 currently supports Forge selection of:

- Datacenter — Desktop Experience
- Standard — Desktop Experience
- Datacenter — Server Core
- Standard — Server Core

Datacenter Desktop Experience is the default.

## End-to-end flow

Linux:

```text
vendor ISO
  ↓
VirtualBox VM
  ↓
zero-touch installation
  ↓
Crucible management network
  ↓
bootstrap
  ↓
SSH
  ↓
ansible.builtin.ping
  ↓
pong
```

Windows:

```text
vendor ISO
  ↓
VirtualBox VM
  ↓
Autounattend.xml + CRUCIBLE_WIN seed ISO
  ↓
zero-touch installation
  ↓
PowerShell bootstrap
  ↓
static management address
  ↓
WinRM HTTPS / PSRP
  ↓
ansible.windows.win_ping
  ↓
pong
```

## Forge capabilities

The v0.2 Forge provides:

- OS selection
- automatic numbered VM naming
- custom VM naming and collision detection
- OS-profile-driven hardware defaults
- configurable CPUs, RAM, disk, VRAM, firmware and graphics
- optional 3D acceleration
- optional additional VirtualBox internal-network NICs
- installation-media discovery
- unattended Linux and Windows installation
- generated credentials
- persistent management-IP allocation
- deterministic management-NIC MAC addresses
- NAT provisioning/Internet NIC
- host-only Crucible management NIC
- runtime Ansible inventory generation
- controller-side readiness checks
- automatic final Ansible ping/pong verification

## Windows provisioning

Windows 10, Windows 11 and Windows Server 2022 share one Windows provisioning backend.

Crucible creates a small ISO labelled `CRUCIBLE_WIN` containing:

```text
Autounattend.xml
bootstrap.ps1
crucible-bootstrap.json
```

`bootstrap.ps1`:

1. finds the Crucible management NIC by deterministic MAC address;
2. assigns its static management IP;
3. prevents it from becoming the default Internet route;
4. enables PowerShell Remoting;
5. creates a self-signed TLS certificate;
6. creates a WinRM HTTPS listener on TCP 5986;
7. restricts the firewall rule to the management network;
8. writes bootstrap success/failure state.

The controller then waits for TCP 5986, establishes PSRP, checks the bootstrap marker, and runs `ansible.windows.win_ping`.

### Server 2022 WIM mapping

For the currently tested ISO:

```text
Index 1 — Standard, Server Core
Index 2 — Standard, Desktop Experience
Index 3 — Datacenter, Server Core
Index 4 — Datacenter, Desktop Experience
```

The Forge records the selected WIM index in the runtime machine manifest and the generated answer file uses `/IMAGE/INDEX`.

## Linux provisioning

Ubuntu Server and Desktop use Subiquity autoinstall with generated NoCloud data.

Kali uses Debian Installer preseeding, a temporary local HTTP preseed service, persistent NetworkManager configuration, and a one-shot first-boot Crucible service.

All Linux guests converge on SSH and `ansible.builtin.ping`.

## Networking

Current default management network:

```text
172.31.0.0/16
```

```text
Controller: 172.31.0.1
Guests:     172.31.0.2 onward
```

Every guest gets at least:

```text
NIC 1 → NAT / Internet / provisioning
NIC 2 → Crucible host-only management
```

Additional NICs can be attached to VirtualBox internal networks.

## Runtime state

Generated state lives under:

```text
.crucible/
├── ansible/
├── generated/
├── manifests/
├── state/
└── vms/
```

`.crucible/` is ignored by Git.

Windows runtime state may contain plaintext generated credentials required for unattended setup and PSRP authentication. Treat it as sensitive local state.

## Requirements

Current primary controller environment: Ubuntu/Linux.

Required or expected:

- Python 3
- VirtualBox / `VBoxManage`
- PyYAML
- Jinja2
- Ansible Core
- `pypsrp`
- OpenSSL
- OpenSSH client
- `xorriso`

Install Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate

python3 -m pip install --upgrade pip
python3 -m pip install PyYAML Jinja2 ansible-core pypsrp

ansible-galaxy collection install -r ansible/requirements.yml
```

Install host utilities on Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip openssl openssh-client xorriso
```

Install VirtualBox separately and verify:

```bash
VBoxManage --version
```

## Installation media

Place vendor ISOs in:

```text
images/iso/
```

Current image IDs:

```text
ubuntu-26.04-server
ubuntu-26.04-desktop
kali-rolling
windows-10
windows-11
windows-server-2022
```

Troubleshoot image detection with:

```bash
python3 -m crucible.provisioning.image_detector --json
```

## Running the Forge

```bash
./crucible.py
```

or:

```bash
python3 crucible.py
```

Do not normally run Crucible with `sudo`.

At v0.2 exactly one VM is supported per Forge invocation.

## Manual Ansible verification

Linux:

```bash
ansible <vm-name> -i .crucible/ansible/inventory.yml -m ansible.builtin.ping
```

Windows:

```bash
ansible <vm-name> -i .crucible/ansible/inventory.yml -m ansible.windows.win_ping
```

Expected:

```text
"ping": "pong"
```

## Current limitations

- VirtualBox is the only implemented hypervisor.
- Ubuntu/Linux is the primary controller environment.
- Only one VM is forged per interactive run.
- Concurrent Forge runs are not supported.
- Cleanup/recovery tooling is still limited.
- The management subnet is currently fixed.
- Post-forge application/service configuration is still minimal.
- The `0.x` CLI, manifests, profiles and internal APIs may change rapidly.

## Version history

### v0.1 — August 19, 2026

First complete zero-touch Ubuntu Server Forge ending in Ansible `pong`.

### v0.1.1 — August 20, 2026

Hardware customization: CPUs, RAM, disk, VRAM, firmware, graphics, 3D acceleration and internal-network NICs.

### v0.1.2 — August 20, 2026

Ubuntu Desktop 26.04 support.

### v0.1.3 — August 20, 2026

Dynamic machine naming, collision detection and management IPAM.

### v0.1.4 — August 20, 2026

Kali Linux Rolling support through Debian preseeding and first-boot bootstrap.

### v0.2 — August 28, 2026

Windows Forge capability:

- Windows 10 Pro
- Windows 11 Pro
- Windows Server 2022
- shared Windows Unattend backend
- shared PowerShell bootstrap
- Server Standard/Datacenter and Core/Desktop selection
- WIM-index-based Server image selection
- static Windows management addressing
- WinRM HTTPS / PSRP
- generated Windows Ansible inventory
- automatic `ansible.windows.win_ping`
- complete Windows `pong`

At v0.2 all six Forge OS choices can be installed and brought to Ansible connectivity without guest-side installation input.

## Candidate directions for v0.3

### Post-forge Ansible configuration

Add optional playbooks/roles after base connectivity, such as:

- common lab packages
- Windows features/roles
- Active Directory preparation
- DNS
- web services
- security tooling
- course-specific baselines

### Multi-VM Forge

Move from one-machine Forge runs to topology-wide construction with multiple OS choices, networks, shared inventory and role assignment.

### Broader compatibility

Future work can validate:

- additional hypervisors
- additional controller operating systems
- additional guest families

This work can proceed when suitable test environments are available.

## Longer-term goal

Crucible is intended to become a reusable cybersecurity-lab construction system: multi-VM topologies, domain controllers, DNS, routers/firewalls, segmented networks, course-specific Ansible roles, snapshots, teardown/rebuild workflows, and eventually additional hypervisors.

The goal is not to automate away the lab. It is to automate the repetitive setup so more time is spent on the systems, protocols, attacks, defenses and troubleshooting the lab is meant to teach.
