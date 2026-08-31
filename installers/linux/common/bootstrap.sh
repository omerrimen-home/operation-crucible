#!/usr/bin/env bash

set -Eeuo pipefail

CRUCIBLE_USER="${1:-crucible}"

LOG_FILE="/var/log/crucible-bootstrap.log"
MARKER_FILE="/var/lib/crucible/bootstrap-complete"

mkdir -p /var/lib/crucible

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo " Operation Crucible - Linux Bootstrap"
echo "=========================================="

echo
echo "[1/5] Verifying Crucible prerequisites..."

if [[ ! -x /usr/sbin/sshd ]]; then
    echo "ERROR: OpenSSH server is not installed."
    exit 1
fi

if [[ ! -x /usr/bin/python3 ]]; then
    echo "ERROR: Python 3 is not installed."
    exit 1
fi

if [[ ! -x /usr/bin/sudo ]]; then
    echo "ERROR: sudo is not installed."
    exit 1
fi

if [[ ! -x /usr/bin/apt-get ]]; then
    echo "ERROR: apt-get is not installed."
    echo "All current Crucible Linux profiles require an APT-based guest."
    exit 1
fi

if ! id "$CRUCIBLE_USER" >/dev/null 2>&1; then
    echo "ERROR: Crucible user does not exist: $CRUCIBLE_USER"
    exit 1
fi

if [[ ! "$CRUCIBLE_USER" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
    echo "ERROR: Invalid Crucible username."
    exit 1
fi

echo "Required packages are available."


# ------------------------------------------------------------
# System update
#
# Operation Crucible now requires Internet connectivity.
#
# apt-get is used instead of apt because apt-get provides a
# stable command-line interface intended for automation.
#
# dist-upgrade provides the same dependency-changing behaviour
# required from a full system upgrade:
#
#   - upgrade installed packages;
#   - install new dependencies when required;
#   - remove obsolete/conflicting dependencies when required.
#
# This is particularly important for Kali Rolling.
# ------------------------------------------------------------

echo
echo "[2/5] Updating installed operating system..."

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
export APT_LISTCHANGES_FRONTEND=none

APT_OPTIONS=(
    -o DPkg::Lock::Timeout=600
    -o Acquire::Retries=5
    -o Acquire::http::Timeout=30
    -o Acquire::https::Timeout=30
    -o Dpkg::Options::=--force-confdef
    -o Dpkg::Options::=--force-confold
)

echo "Refreshing APT package metadata..."

apt-get \
    "${APT_OPTIONS[@]}" \
    update

echo
echo "Performing full system upgrade..."

apt-get \
    "${APT_OPTIONS[@]}" \
    -y \
    dist-upgrade

echo
echo "System package upgrade complete."

if [[ -f /var/run/reboot-required ]]; then
    echo "A reboot is required to activate one or more installed updates."
fi


# ------------------------------------------------------------
# Crucible privilege escalation
# ------------------------------------------------------------

echo
echo "[3/5] Configuring Crucible privilege escalation..."

install -d -m 0755 /etc/sudoers.d

SUDOERS_FILE="/etc/sudoers.d/90-crucible"

printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' \
    "$CRUCIBLE_USER" \
    > "$SUDOERS_FILE"

chmod 0440 "$SUDOERS_FILE"

if ! /usr/sbin/visudo -cf "$SUDOERS_FILE"; then
    echo "ERROR: Generated sudoers configuration is invalid."
    rm -f "$SUDOERS_FILE"
    exit 1
fi

echo "Passwordless sudo configured for $CRUCIBLE_USER."


# ------------------------------------------------------------
# SSH
# ------------------------------------------------------------

echo
echo "[4/5] Configuring SSH..."

install -d -m 0755 /etc/ssh/sshd_config.d

cat > /etc/ssh/sshd_config.d/00-crucible.conf <<'EOF'
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PasswordAuthentication yes
PermitRootLogin no
EOF

systemctl enable ssh.service

# Ubuntu may execute this bootstrap through curtin/in-target
# before the installed OS has booted normally.
#
# Kali executes the same bootstrap during first boot.
#
# Therefore the restart is intentionally best-effort.
systemctl restart ssh.service >/dev/null 2>&1 || true


# ------------------------------------------------------------
# Completion
# ------------------------------------------------------------

echo
echo "[5/5] Marking bootstrap complete..."

date --iso-8601=seconds > "$MARKER_FILE"

echo
echo "Crucible bootstrap complete."
echo "Operating system fully upgraded."
echo "SSH enabled."
echo "Python available for Ansible."
echo "Privilege escalation available for configuration roles."