#!/usr/bin/env bash

set -Eeuo pipefail

LOG_FILE="/var/log/crucible-bootstrap.log"
MARKER_FILE="/var/lib/crucible/bootstrap-complete"

mkdir -p /var/lib/crucible

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo " Operation Crucible - Linux Bootstrap"
echo "=========================================="

echo "[1/3] Verifying Crucible prerequisites..."

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

echo "Required packages are available."

echo "[2/3] Configuring SSH..."

install -d -m 0755 /etc/ssh/sshd_config.d

cat > /etc/ssh/sshd_config.d/00-crucible.conf <<'EOF'
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
PasswordAuthentication yes
PermitRootLogin no
EOF

systemctl enable ssh.service

# Ubuntu may execute this script from curtin/in-target while
# the installed system is not yet booted. Starting/restarting
# sshd is therefore best-effort here. Kali runs this at first
# boot, where the restart will normally succeed.
systemctl restart ssh.service >/dev/null 2>&1 || true

echo "[3/3] Marking bootstrap complete..."

date --iso-8601=seconds > "$MARKER_FILE"

echo
echo "Crucible bootstrap complete."
echo "SSH enabled."
echo "Python available for Ansible."