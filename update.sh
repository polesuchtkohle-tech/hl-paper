#!/usr/bin/env bash
# update.sh — Code auf VM aktualisieren und Bot neu starten.
# Aufruf: bash update.sh

set -euo pipefail

VM="poles@35.240.64.29"
DIR="hl-paper"

echo "=== Update wird eingespielt ==="

# Lokal committen und pushen
git add -A
git commit -m "update: $(date -u '+%Y-%m-%d %H:%M UTC')" || echo "(nichts zu committen)"
git push

# Auf VM: pullen und neu starten
ssh "$VM" bash <<EOF
export PATH="\$HOME/.local/bin:\$PATH"
cd $DIR
git pull
uv sync --quiet

# Bot neu starten
screen -S paper-trader -X quit 2>/dev/null || true
sleep 2
screen -dmS paper-trader bash -c "uv run python runner.py 2>&1 | tee logs/runner.log"
echo "Bot neu gestartet."
EOF

echo ""
echo "Fertig. Status:"
ssh "$VM" "cd $DIR && uv run python status.py 2>/dev/null || echo '(noch keine Daten)'"
