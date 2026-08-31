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
echo "[1/4] Verifying Crucible prerequisites..."

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

if ! id "$CRUCIBLE_USER" >/dev/null 2>&1; then
    echo "ERROR: Crucible user does not exist: $CRUCIBLE_USER"
    exit 1
fi

if [[ ! "$CRUCIBLE_USER" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]]; then
    echo "ERROR: Invalid Crucible username."
    exit 1
fi

echo "Required packages are available."

echo
echo "[2/4] Configuring Crucible privilege escalation..."

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

echo
echo "[3/4] Configuring SSH..."

install -d -m 0755 /etc/ssh/sshd_config.d

cat > /etc/ssh/sshd_config.d/00-crucible.conf <<'EOF'
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PasswordAuthentication yes
PermitRootLogin no
EOF

systemctl enable ssh.service

systemctl restart ssh.service >/dev/null 2>&1 || true

echo
echo "[4/4] Marking bootstrap complete..."

date --iso-8601=seconds > "$MARKER_FILE"

echo
echo "Crucible bootstrap complete."
echo "SSH enabled."
echo "Python available for Ansible."
echo "Privilege escalation available for configuration roles."