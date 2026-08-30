# Operation Crucible

**Current release: v0.2.1**  
**Status: early alpha**  
**Controller: Linux / Ubuntu**  
**Hypervisor: Oracle VirtualBox**  
**Topology limit: one VM per Forge invocation**

Operation Crucible is a local cybersecurity-lab automation framework for rapidly constructing disposable virtual machines from ordinary vendor installation media.

The Forge handles VM creation, hardware configuration, unattended operating-system installation, lab networking, management connectivity, bootstrap, and final Ansible verification.

A successful Forge run does not stop when the guest reaches a login screen. Crucible waits until the machine is manageable and verifies the result with an Ansible `pong`.

---

## Supported Guests

| Operating system | Installer backend | Status | Management |
|---|---|---:|---|
| Ubuntu Server 26.04 | Subiquity / NoCloud | ✅ | SSH + Ansible |
| Ubuntu Desktop 26.04 | Subiquity / NoCloud | ✅ | SSH + Ansible |
| Kali Linux Rolling | Debian Installer Preseed | ✅ | SSH + Ansible |
| Windows 10 Pro | Windows Unattend | ✅ | WinRM HTTPS / PSRP + Ansible |
| Windows 11 Pro | Windows Unattend | ✅ | WinRM HTTPS / PSRP + Ansible |
| Windows Server 2022 | Windows Unattend | ✅ | WinRM HTTPS / PSRP + Ansible |

All six guest choices have been tested with the v0.2.1 networking and management model.

### Windows Server 2022 Editions

Windows Server 2022 currently supports Forge selection of:

- Standard — Server Core
- Standard — Desktop Experience
- Datacenter — Server Core
- Datacenter — Desktop Experience

Datacenter Desktop Experience is the default.

---

## Current Forge Flow

### Linux

```text
vendor ISO
  ↓
VirtualBox VM
  ↓
generated unattended installation data
  ↓
zero-touch OS installation
  ↓
persistent topology networking
  ↓
Crucible management networking
  ↓
Linux bootstrap
  ↓
per-instance SSH authentication
  ↓
generated Ansible inventory
  ↓
ansible.builtin.ping
  ↓
pong
```

### Windows

```text
vendor ISO
  ↓
VirtualBox VM
  ↓
Autounattend.xml + CRUCIBLE_WIN seed ISO
  ↓
zero-touch OS installation
  ↓
PowerShell bootstrap
  ↓
persistent topology networking
  ↓
static Crucible management address
  ↓
WinRM HTTPS / PSRP
  ↓
generated Ansible inventory
  ↓
ansible.windows.win_ping
  ↓
pong
```

---

## Forge Capabilities

Crucible v0.2.1 currently provides:

- six supported guest operating-system choices;
- automatic numbered VM naming;
- custom VM names with collision detection;
- OS-profile-driven hardware defaults;
- configurable CPU count;
- configurable RAM;
- configurable virtual disk size;
- configurable VRAM;
- configurable firmware;
- configurable graphics controller;
- optional 3D acceleration;
- persistent topology interfaces;
- VirtualBox Internal Network topology attachments;
- VirtualBox Bridged Adapter topology attachments;
- DHCP or static IPv4 topology configuration;
- optional static default gateways;
- deterministic topology NIC MAC addresses;
- deterministic Crucible NAT MAC addresses;
- deterministic Crucible management MAC addresses;
- installation-media discovery;
- unattended Linux installation;
- unattended Windows installation;
- generated guest credentials;
- persistent Crucible management IP allocation;
- unique per-instance Linux SSH identities;
- isolated per-instance SSH host-key trust;
- runtime machine and lab manifests;
- runtime Ansible inventory generation;
- automatic bootstrap readiness checks;
- automatic SSH or PSRP management verification;
- automatic final Ansible ping/pong verification.

---

# Networking

Networking was substantially redesigned in v0.2.1.

Crucible now distinguishes between:

```text
persistent lab topology
```

and:

```text
temporary Crucible infrastructure
```

The topology interfaces represent the actual cybersecurity lab.

The Crucible Internet and management adapters exist to provision and manage the lab.

---

## NIC Ordering

Persistent user-defined topology interfaces always receive the lowest VirtualBox NIC slots.

Crucible infrastructure is appended afterward.

```text
NIC 1..N   → persistent topology interfaces
NIC N+1    → Crucible NAT / Internet / provisioning
NIC N+2    → Crucible management
```

### No Topology Interfaces

```text
NIC 1 → Crucible NAT
NIC 2 → Crucible management
```

### One Topology Interface

```text
NIC 1 → topology
NIC 2 → Crucible NAT
NIC 3 → Crucible management
```

### Two Topology Interfaces

```text
NIC 1 → topology
NIC 2 → topology
NIC 3 → Crucible NAT
NIC 4 → Crucible management
```

This ordering is intentional.

Future Crucible versions will be able to remove temporary provisioning and management adapters without changing the interface numbering of the actual lab topology.

VirtualBox currently exposes a maximum of eight NIC slots per VM.

Because Crucible reserves two of those slots for Internet and management infrastructure, up to six persistent topology interfaces can currently be defined.

---

## Persistent Topology Interfaces

Each topology interface has its own:

```text
label
slot
deterministic MAC address
attachment type
IPv4 configuration
```

Supported attachment types are currently:

```text
VirtualBox Internal Network
VirtualBox Bridged Adapter
```

Internal networks can be used to construct isolated lab segments.

Bridged adapters can attach a VM directly to an appropriate physical or host network.

---

## IPv4 Configuration

Each persistent topology interface can use either:

```text
DHCP
```

or:

```text
Static IPv4
```

Static configuration accepts:

```text
IPv4 address
subnet mask
optional default gateway
```

Crucible validates the values and normalizes static addressing into CIDR form before storing it in the generated machine manifest.

Example:

```text
Address:      192.168.50.10
Subnet mask:  255.255.255.0
Gateway:      192.168.50.1
```

becomes:

```text
192.168.50.10/24
```

with:

```text
gateway: 192.168.50.1
```

A topology interface does not require a default gateway.

This is useful for isolated LANs, server segments, router labs, DNS networks, DHCP networks, and other multi-interface configurations.

---

## Route Preference

While the temporary Crucible NAT adapter exists, Crucible prefers it for Internet access and provisioning.

Topology routes remain configured but rank below the provisioning route.

This allows a machine to contain a realistic lab topology while still using VirtualBox NAT during construction.

The topology itself remains independent of Crucible management infrastructure.

---

# Crucible Management Network

The default Crucible management network is:

```text
172.31.0.0/16
```

Current addressing begins with:

```text
Controller: 172.31.0.1
Guests:     172.31.0.2 onward
```

Management addresses are allocated by Crucible's local IPAM state.

The management interface is designed strictly for controller-to-guest automation and is not intended to become the guest's default Internet route.

---

# Linux Provisioning

Ubuntu and Kali use separate unattended installation systems but converge on the same management model.

---

## Ubuntu Server and Desktop

Ubuntu Server and Ubuntu Desktop use Subiquity autoinstall with generated NoCloud configuration.

Crucible dynamically generates:

```text
user-data
meta-data
```

The autoinstall configuration includes:

- guest identity;
- locale;
- timezone;
- keyboard layout;
- disk layout;
- SSH server installation;
- Crucible SSH public key;
- persistent topology interfaces;
- Crucible NAT networking;
- Crucible management networking;
- bootstrap execution.

Network interfaces are matched by deterministic MAC address rather than relying on fixed Linux interface names.

This allows the NAT and management NICs to move as topology interfaces are added.

---

## Kali Linux

Kali Linux Rolling uses Debian Installer preseeding.

The Forge generates a preseed configuration and temporarily serves it from the controller over HTTP.

Because the NAT adapter may no longer be NIC 1, Crucible dynamically determines:

```text
Kali installer interface
VirtualBox NAT slot
VirtualBox NAT guest-to-host address
```

For example:

```text
NIC 1 → topology
NIC 2 → topology
NIC 3 → NAT
NIC 4 → management
```

causes Kali's installer NAT interface to use the VirtualBox NAT network corresponding to NIC 3.

The completed Kali installation uses persistent NetworkManager connection profiles matched by deterministic MAC address.

Crucible creates profiles for:

```text
topology interfaces
Crucible NAT
Crucible management
```

Static and DHCP topology configurations are supported.

---

# Linux SSH Management

Crucible v0.2.1 no longer depends on the controller user's normal SSH keypair for Linux automation.

Every newly forged Linux VM instance receives its own dedicated Ed25519 management identity.

Example runtime directory:

```text
.crucible/
└── ssh/
    └── machines/
        └── ubuntu-server-01-CRU-A19F82C44310/
            ├── id_ed25519
            ├── id_ed25519.pub
            └── known_hosts
```

The generated public key is injected into the guest during unattended installation.

The matching private key remains on the controller and is used by Crucible and Ansible.

---

## Instance Serials

Each newly forged instance receives a unique serial similar to:

```text
CRU-A19F82C44310
```

The machine name describes the logical VM:

```text
ubuntu-server-01
```

The instance serial identifies that particular installation of the VM.

This distinction becomes important when disposable machines are repeatedly deleted and recreated with the same logical name.

---

## SSH Host-Key Isolation

Disposable VMs frequently reuse management IP addresses.

Using the controller's normal:

```text
~/.ssh/known_hosts
```

would therefore cause stale SSH host-key collisions whenever a VM was rebuilt.

Crucible instead maintains a dedicated `known_hosts` file for every forged VM instance.

This isolates Crucible from the user's personal SSH trust database.

The Linux readiness sequence is approximately:

```text
TCP/22 reachable
  ↓
bootstrap transition
  ↓
final installed OS available
  ↓
final guest SSH host key accepted
  ↓
per-instance client key authentication
  ↓
Ansible
```

Installer-stage SSH identity is not treated as the permanent identity of the finished guest.

---

# Linux Bootstrap

Ubuntu and Kali share a small common Linux bootstrap.

The bootstrap verifies that the unattended installer has already provided the required base components:

```text
OpenSSH Server
Python 3
sudo
```

It then ensures SSH is configured appropriately for Crucible and writes:

```text
/var/lib/crucible/bootstrap-complete
```

Crucible waits for this marker before treating the Linux guest as fully bootstrapped.

The bootstrap intentionally does not require a full package update or upgrade.

This keeps VM construction independent from repository availability and prevents unnecessary package-network operations from blocking the Forge.

---

# Windows Provisioning

Windows 10, Windows 11 and Windows Server 2022 use a shared Windows provisioning backend.

Crucible creates a small generated ISO labelled:

```text
CRUCIBLE_WIN
```

containing:

```text
Autounattend.xml
bootstrap.ps1
crucible-bootstrap.json
```

The Windows bootstrap:

1. identifies Crucible-managed NICs by deterministic MAC address;
2. configures the management interface;
3. configures persistent topology interfaces;
4. handles DHCP or static IPv4 topology configuration;
5. applies route preference;
6. prevents the management interface from becoming the default Internet route;
7. enables PowerShell Remoting;
8. creates a self-signed TLS certificate;
9. creates a WinRM HTTPS listener;
10. restricts the management firewall rule;
11. records bootstrap completion or failure state.

The controller then establishes PSRP connectivity and performs:

```text
ansible.windows.win_ping
```

---

## Windows Server 2022 WIM Selection

For the currently tested Windows Server 2022 installation media:

```text
Index 1 → Standard, Server Core
Index 2 → Standard, Desktop Experience
Index 3 → Datacenter, Server Core
Index 4 → Datacenter, Desktop Experience
```

The Forge records the selected WIM index and injects it into the generated answer file using:

```text
/IMAGE/INDEX
```

---

# Machine Manifests

Crucible resolves Forge selections into runtime machine manifests.

Generated manifests currently use schema version 2.

A machine manifest contains information such as:

```text
instance identity
OS profile
installation image
hardware resources
VirtualBox settings
persistent topology
Internet overlay
management overlay
autoinstall configuration
startup behavior
```

Example network structure:

```yaml
network:
  topology:
    - label: lan
      slot: 1
      mac_address: "02:AA:BB:CC:DD:EE"
      attachment:
        type: intnet
        network: LAB-LAN
      ipv4:
        method: static
        address: 192.168.50.10/24
        gateway: null

  internet:
    enabled: true
    slot: 2
    mode: nat

  management:
    enabled: true
    slot: 3
    address: 172.31.0.4/16
```

Generated manifests live under `.crucible/` and should normally be treated as runtime state rather than manually maintained configuration.

---

# Runtime State

Crucible-generated local state lives under:

```text
.crucible/
├── ansible/
│   └── inventory.yml
├── generated/
│   ├── autoinstall/
│   ├── preseed/
│   └── windows/
├── manifests/
│   ├── labs/
│   └── machines/
├── ssh/
│   └── machines/
├── state/
└── vms/
```

`.crucible/` is excluded from Git.

This directory can contain sensitive runtime material, including:

```text
Linux SSH private keys
Windows generated passwords
generated Ansible connection data
machine-specific installer data
```

Treat `.crucible/` as private controller state.

---

# Installation Media

Large vendor installation ISOs are intentionally not stored in the Git repository.

Place source ISOs in:

```text
images/iso/
```

Current image IDs are:

```text
ubuntu-26.04-server
ubuntu-26.04-desktop
kali-rolling
windows-10
windows-11
windows-server-2022
```

Kali must use the installer image rather than the Live image.

Image recognition is configured through:

```text
config/images.yml
```

Troubleshoot media detection with:

```bash
python3 -m crucible.provisioning.image_detector --json
```

---

# Requirements

The current primary controller environment is Ubuntu/Linux.

Required or expected components include:

```text
Python 3
Oracle VirtualBox / VBoxManage
PyYAML
Jinja2
Ansible Core
pypsrp
OpenSSL
OpenSSH client
xorriso
```

Create a Python virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install Python dependencies:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install \
    PyYAML \
    Jinja2 \
    ansible-core \
    pypsrp
```

Install required Ansible collections:

```bash
ansible-galaxy collection install \
    -r ansible/requirements.yml
```

On Ubuntu, useful host packages include:

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

Install VirtualBox separately and verify:

```bash
VBoxManage --version
```

---

# Running the Forge

Start the interactive Forge with:

```bash
./crucible.py
```

or:

```bash
python3 crucible.py
```

Do not normally run Crucible with `sudo`.

The Forge will guide the user through:

```text
VM count
OS selection
machine naming
hardware configuration
topology-interface configuration
unattended-install configuration
Forge confirmation
VM construction
management verification
Ansible verification
```

At v0.2.1, exactly one VM is supported per Forge invocation.

---

# Manual Ansible Verification

Crucible automatically performs this verification at the end of a successful Forge.

It can also be repeated manually.

### Linux

```bash
ansible <vm-name> \
    -i .crucible/ansible/inventory.yml \
    -m ansible.builtin.ping
```

### Windows

```bash
ansible <vm-name> \
    -i .crucible/ansible/inventory.yml \
    -m ansible.windows.win_ping
```

Expected result:

```text
"ping": "pong"
```

Linux inventory entries reference the appropriate per-instance private SSH key and per-instance `known_hosts` file under `.crucible/`.

---

# Repository Layout

Major repository areas currently include:

```text
operation-crucible/
├── ansible/
│   ├── inventories/
│   ├── playbooks/
│   ├── roles/
│   └── requirements.yml
│
├── config/
│   └── images.yml
│
├── crucible/
│   ├── cli/
│   ├── hypervisors/
│   ├── inventory/
│   ├── networking/
│   ├── provisioning/
│   ├── ssh/
│   └── validation/
│
├── images/
│   ├── generated/
│   └── iso/
│
├── installers/
│   ├── linux/
│   │   ├── common/
│   │   ├── kali/
│   │   └── ubuntu/
│   └── windows/
│
├── manifests/
│   ├── labs/
│   └── machines/
│
├── profiles/
│   └── os/
│
├── tests/
│
└── crucible.py
```

`crucible.py` currently provides the primary interactive Forge interface.

The modules beneath `crucible/` contain the reusable implementation layers.

---

# Automated Tests

Current unit-test coverage includes the new network model.

Run tests with:

```bash
python3 -m unittest discover \
    -s tests \
    -v
```

Current test coverage includes:

```text
canonical NIC layout
maximum topology-interface count
legacy Linux slot/interface mapping
subnet-mask conversion
DHCP IPv4 structures
static IPv4 normalization
gateway validation
deterministic topology MAC generation
```

Full operating-system Forge validation remains an integration test requiring VirtualBox and vendor installation media.

---

# Current Limitations

Crucible remains an early `0.x` project.

Current limitations include:

- Oracle VirtualBox is the only implemented hypervisor.
- Ubuntu/Linux is the primary controller environment.
- Exactly one VM is forged per interactive run.
- Concurrent Forge runs are not supported.
- Multi-machine topology lifecycle management is not yet implemented.
- Crucible infrastructure NIC teardown is not yet implemented.
- The management subnet is currently fixed.
- Cleanup and recovery tooling remains limited.
- Post-forge application and service configuration is still minimal.
- Persistent saved/re-enterable topology management is not yet implemented.
- CLI behavior, manifests, profiles and internal APIs may change rapidly during `0.x`.

---

# Version History

## v0.1 — August 19, 2026

First complete zero-touch Ubuntu Server Forge ending in Ansible `pong`.

The initial Forge established the base project workflow:

```text
VM creation
  ↓
Ubuntu unattended installation
  ↓
SSH
  ↓
Ansible
  ↓
pong
```

---

## v0.1.1 — August 20, 2026

Added hardware customization:

```text
CPUs
RAM
disk size
VRAM
firmware
graphics controller
3D acceleration
additional internal-network NICs
```

---

## v0.1.2 — August 20, 2026

Added Ubuntu Desktop 26.04 support.

---

## v0.1.3 — August 20, 2026

Added:

```text
dynamic machine naming
collision detection
persistent management IPAM
```

---

## v0.1.4 — August 20, 2026

Added Kali Linux Rolling support through Debian Installer preseeding and a first-boot Crucible bootstrap.

---

## v0.2 — August 28, 2026

Introduced complete Windows Forge support.

Added:

```text
Windows 10 Pro
Windows 11 Pro
Windows Server 2022
shared Windows Unattend backend
shared PowerShell bootstrap
Server Standard / Datacenter selection
Server Core / Desktop Experience selection
WIM-index-based Windows Server selection
static Windows management addressing
WinRM HTTPS
PSRP
generated Windows Ansible inventory
ansible.windows.win_ping
```

At v0.2, all six Forge OS choices could be installed and brought to Ansible connectivity without guest-side installation input.

---

## v0.2.1 — August 30, 2026

Networking and Linux management-identity refinement release.

### Persistent Topology Networking

Topology interfaces now occupy the lowest VirtualBox NIC slots.

Crucible NAT and management adapters are appended after the persistent topology.

Added:

```text
VirtualBox Internal Network topology interfaces
VirtualBox Bridged Adapter topology interfaces
DHCP topology configuration
static IPv4 topology configuration
optional topology default gateways
deterministic topology MAC addresses
deterministic Crucible NAT MAC addresses
canonical NIC layout validation
```

Ubuntu, Kali and Windows provisioning were updated to support dynamically positioned infrastructure NICs.

### Kali Networking Improvements

Kali provisioning was updated for the new NIC model.

Changes include:

```text
dynamic installer-interface selection
slot-aware VirtualBox NAT preseed delivery
persistent NetworkManager keyfiles
MAC-based interface matching
multi-topology-interface support
static topology addressing
DHCP topology addressing
route preference
```

### Per-Instance Linux SSH Identity

Every Linux Forge now creates a unique Ed25519 management identity.

Added:

```text
per-instance SSH private key
per-instance SSH public key
per-instance known_hosts
unique CRU-* instance serial
automatic guest public-key injection
isolated SSH host-key trust
```

Crucible no longer relies on the user's personal `~/.ssh` identity or trust database for automated Linux management.

### Bootstrap Improvements

Linux bootstrap was simplified so Forge completion does not depend on performing package updates or upgrades.

SSH readiness now distinguishes between:

```text
installer / transitional state
```

and:

```text
final installed guest identity
```

This avoids stale SSH host-key problems while disposable VMs reuse management addresses.

### Validation

The v0.2.1 networking model has been successfully tested with all six supported Forge choices:

```text
Ubuntu Server 26.04
Ubuntu Desktop 26.04
Kali Linux Rolling
Windows 10 Pro
Windows 11 Pro
Windows Server 2022
```

---

# Planned v0.3 Direction

v0.2.1 establishes the network and management foundation needed for declarative post-install configuration.

The next major development stage is intended to add a configuration catalog and Ansible role execution after base connectivity has been established.

---

## Configuration Catalog

A planned:

```text
config/configurations.yml
```

will describe optional post-install configurations.

Configuration definitions are expected to declare information such as:

```text
supported operating systems
required network topology
required static addressing
Ansible implementation
configuration-specific parameters
```

The Forge will only expose configurations compatible with the selected guest.

If a configuration requires networking that has not yet been defined, the Forge can return the user to topology configuration rather than failing later during Ansible execution.

---

## Initial Planned Configurations

Early configuration targets include:

```text
Ubuntu LTS CIS-aligned baseline hardening
restrictive Linux nftables firewall
Windows Server Active Directory Domain Controller
authoritative DNS server
DHCP server
```

Cross-platform services such as DNS and DHCP will eventually abstract different implementations behind a common Crucible configuration.

Examples:

```text
Linux DNS   → BIND9
Windows DNS → Windows DNS Server

Linux DHCP   → Kea DHCP
Windows DHCP → Windows DHCP Server
```

---

## Planned v0.3 Forge Lifecycle

The Forge will eventually expand from:

```text
install
  ↓
bootstrap
  ↓
management verification
  ↓
Ansible pong
```

to:

```text
install
  ↓
bootstrap
  ↓
management verification
  ↓
Ansible connectivity
  ↓
selected Crucible configurations
  ↓
configuration validation
  ↓
Forge complete
```

---

# Longer-Term Direction

Operation Crucible is intended to grow into a reusable cybersecurity-lab construction system.

Future capabilities may include:

```text
multi-VM Forge runs
saved lab topologies
shared internal networks
Active Directory forests and domains
primary and secondary DNS
DHCP servers
DHCP relay
routers and packet forwarding
firewalls
segmented networks
course-specific Ansible roles
snapshots
teardown and rebuild workflows
additional hypervisors
additional controller operating systems
additional guest operating systems
```

Multi-machine support will allow Crucible to move from constructing individual systems to constructing complete lab environments.

The long-term goal is not to automate away the lab itself.

The goal is to automate the repetitive infrastructure setup so that more time can be spent working with the systems, protocols, attacks, defenses and troubleshooting that the lab is intended to teach.