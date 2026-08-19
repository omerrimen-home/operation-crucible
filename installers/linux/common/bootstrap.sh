#!/usr/bin/env bash

set -Eeuo pipefail

export DEBIAN_FRONTEND=noninteractive

LOG_FILE="/var/log/crucible-bootstrap.log"
MARKER_FILE="/var/lib/crucible/bootstrap-complete"

mkdir -p /var/lib/crucible

exec > >(tee -a "$LOG_FILE") 2>&1

echo "=========================================="
echo " Operation Crucible - Linux Bootstrap"
echo "=========================================="

echo "[1/5] Updating package indexes..."
apt-get update

echo "[2/5] Upgrading installed packages..."
apt-get \
    -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    upgrade

echo "[3/5] Installing Crucible base packages..."
apt-get install -y \
    openssh-server \
    python3 \
    python3-apt \
    sudo \
    ca-certificates

echo "[4/5] Configuring SSH..."

mkdir -p /etc/ssh/sshd_config.d

cat > /etc/ssh/sshd_config.d/99-crucible.conf <<'EOF'
PubkeyAuthentication yes
PasswordAuthentication yes
PermitRootLogin no
EOF

systemctl enable ssh.service

echo "[5/5] Marking bootstrap complete..."

date --iso-8601=seconds > "$MARKER_FILE"

echo
echo "Crucible bootstrap complete."
echo "SSH enabled."
echo "Python available for Ansible."

mkdir -p /var/lib/crucible
date --iso-8601=seconds > /var/lib/crucible/bootstrap-complete