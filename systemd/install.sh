#!/usr/bin/env bash
# Installationsskript fuer den Paper-Trader auf einer Linux VM (GCP)
# Aufruf: sudo bash systemd/install.sh

set -euo pipefail

INSTALL_DIR="/opt/paper-trader"
SERVICE_USER="paper"

echo "=== Paper-Trader Installation ==="

# 1. Benutzer anlegen (falls nicht vorhanden)
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "Benutzer '$SERVICE_USER' angelegt."
fi

# 2. Installationsverzeichnis
mkdir -p "$INSTALL_DIR"
cp -r . "$INSTALL_DIR/"
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

# 3. .env pruefen
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    echo "WARNUNG: .env von .env.example kopiert. Bitte anpassen!"
fi

# 4. uv installieren (falls nicht vorhanden)
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# 5. Python-Abhaengigkeiten installieren
cd "$INSTALL_DIR"
uv sync

# 6. systemd-Services installieren
cp systemd/paper-trader.service  /etc/systemd/system/
cp systemd/paper-cleanup.service /etc/systemd/system/
cp systemd/paper-cleanup.timer   /etc/systemd/system/
cp systemd/paper-report.service  /etc/systemd/system/
cp systemd/paper-report.timer    /etc/systemd/system/

# 7. systemd aktualisieren und aktivieren
systemctl daemon-reload
systemctl enable --now paper-trader.service
systemctl enable --now paper-cleanup.timer
systemctl enable --now paper-report.timer

echo ""
echo "=== Installation abgeschlossen ==="
echo ""
echo "Befehle:"
echo "  systemctl status paper-trader    # Status pruefen"
echo "  journalctl -fu paper-trader      # Logs live"
echo "  python status.py                 # Uebersicht"
echo "  systemctl stop paper-trader      # Stoppen"
echo ""
echo "Testmodus starten:"
echo "  systemctl stop paper-trader"
echo "  cd $INSTALL_DIR"
echo "  uv run python runner.py --testmodus"
