#!/usr/bin/env bash
# VHS-Sat Linux installer (Debian / Ubuntu)
#
# Usage:
#   sudo bash install-linux.sh                    # install to /opt/vhs-sat
#   sudo bash install-linux.sh --dir /srv/vhs-sat # custom dir
#   sudo bash install-linux.sh --no-service       # no systemd unit
#
# Must be run from the extracted VHS-Sat source directory.

set -euo pipefail

# ---------- defaults ----------
INSTALL_DIR="${INSTALL_DIR:-/opt/vhs-sat}"
SERVICE_USER="${SERVICE_USER:-vhs-sat}"
SERVICE_NAME="vhs-sat"
SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}.service"
WITH_SERVICE=1

# ---------- arg parser ----------
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dir)         INSTALL_DIR="$2"; shift 2 ;;
        --user)        SERVICE_USER="$2"; shift 2 ;;
        --no-service)  WITH_SERVICE=0; shift ;;
        --help|-h)
            echo "Usage: sudo bash $0 [--dir PATH] [--user NAME] [--no-service]"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ---------- colors ----------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
info()  { printf "${GREEN}[+]${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
error() { printf "${RED}[x]${NC} %s\n" "$*" >&2; }

# ---------- checks ----------
if [ "$EUID" -ne 0 ]; then
    error "Run as root: sudo bash $0"
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    error "This installer supports Debian/Ubuntu only (apt-get not found)."
    error "For other distros, install manually:"
    error "  - python3, python3-venv, python3-pip"
    error "  - ffmpeg (for HLS streaming)"
    error "  - dvb-tools (for dvbv5-zap, dvbv5-scan, dvb-fe-tool)"
    error "  - dvblast (for multicast MPEG-TS)"
    exit 1
fi

# Find source directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -f "$SCRIPT_DIR/server.py" ]; then
    error "server.py not found in $SCRIPT_DIR"
    error "Run this script from the extracted VHS-Sat source directory."
    exit 1
fi

info "Source: $SCRIPT_DIR"
info "Install dir: $INSTALL_DIR"
info "Service user: $SERVICE_USER"

# ---------- system packages ----------
info "Installing system packages (this may take a few minutes)..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    ffmpeg \
    dvb-tools \
    dvblast \
    curl

# ---------- user ----------
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    info "Creating system user: $SERVICE_USER"
    useradd --system --home "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if getent group video >/dev/null 2>&1; then
    info "Adding $SERVICE_USER to 'video' group (for /dev/dvb access)"
    usermod -aG video "$SERVICE_USER" 2>/dev/null || true
else
    warn "Group 'video' not found — DVB hardware access may require manual setup"
fi

# ---------- copy source ----------
info "Copying source to $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
tar --exclude='.git' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='dist' \
    --exclude='build' \
    --exclude='vendor' \
    --exclude='data' \
    --exclude='logs' \
    --exclude='config.yaml' \
    --exclude='*.db' \
    -czf - -C "$SCRIPT_DIR" . | tar -xzf - -C "$INSTALL_DIR"

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# ---------- venv ----------
info "Creating Python venv and installing dependencies..."
sudo -u "$SERVICE_USER" python3 -m venv "$INSTALL_DIR/venv"
sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
if [ -f "$INSTALL_DIR/requirements.txt" ]; then
    sudo -u "$SERVICE_USER" "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
fi

# ---------- config ----------
if [ ! -f "$INSTALL_DIR/config.yaml" ] && [ -f "$INSTALL_DIR/config.example.yaml" ]; then
    info "Creating config.yaml from config.example.yaml"
    cp "$INSTALL_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/config.yaml"
fi

# ---------- systemd ----------
if [ "$WITH_SERVICE" -eq 1 ]; then
    info "Installing systemd service: $SYSTEMD_UNIT"
    cat > "$SYSTEMD_UNIT" <<EOF
[Unit]
Description=VHS-Sat — satellite TV relay server
Documentation=https://github.com/andrey-geben/VHS-Sat
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/server.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        info "Service started successfully"
    else
        warn "Service not running — check: journalctl -u $SERVICE_NAME -n 50"
    fi
fi

# ---------- firewall ----------
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    info "Opening firewall ports (ufw)..."
    ufw allow 8300/tcp comment 'VHS-Sat admin' || true
    ufw allow 8301/tcp comment 'VHS-Sat viewer' || true
    ufw allow 5000:5100/udp comment 'VHS-Sat multicast' || true
fi

# ---------- summary ----------
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$IP" ] && IP="<server-ip>"

echo ""
info "==================================================="
info " VHS-Sat installed"
info "==================================================="
info ""
info " Web UI:  http://$IP:8300/setup"
info " Viewer:  http://$IP:8301/"
info ""

if [ "$WITH_SERVICE" -eq 1 ]; then
    info " Systemd commands:"
    info "   systemctl status $SERVICE_NAME   # status"
    info "   systemctl restart $SERVICE_NAME  # restart"
    info "   systemctl stop $SERVICE_NAME     # stop"
    info "   journalctl -u $SERVICE_NAME -f   # live logs"
    info ""
fi

info " Files:"
info "   Config: $INSTALL_DIR/config.yaml"
info "   Data:   $INSTALL_DIR/data/"
info "   Logs:   $INSTALL_DIR/logs/events.jsonl"
info ""

if [ ! -d /dev/dvb ]; then
    warn "No /dev/dvb/ directory found."
    warn "DVB-S/S2 channels will be unavailable."
    warn "If you have a DVB card, check drivers:  dmesg | grep -i dvb"
    warn ""
fi

info " Next steps:"
info "  1. Open http://$IP:8300/setup in browser"
info "  2. Create admin (username + password)"
info "  3. Go to /channels → create channels"
info "  4. For DVB: check /hardware, then /adapters"
info ""