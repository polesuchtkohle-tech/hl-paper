#!/usr/bin/env bash
# deploy.sh — Einmaliges Setup auf der VM.
# Aufruf: bash deploy.sh
# Danach laeuft der Bot dauerhaft im Hintergrund.

set -euo pipefail

VM="poles@35.240.64.29"
REPO="https://github.com/DEIN-NAME/hl-paper.git"   # <-- anpassen!
DIR="hl-paper"

echo "=== Paper-Trader Deployment ==="

ssh "$VM" bash <<EOF
set -euo pipefail

# uv installieren falls nicht vorhanden
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source ~/.bashrc || source ~/.profile
fi
export PATH="\$HOME/.local/bin:\$PATH"

# Repo klonen oder updaten
if [ -d "$DIR" ]; then
    echo "Repo vorhanden, update..."
    cd $DIR && git pull
else
    git clone $REPO $DIR
    cd $DIR
fi

# Dependencies installieren
uv sync

# Laufenden Bot stoppen falls vorhanden
if screen -list | grep -q paper-trader; then
    screen -S paper-trader -X quit || true
    sleep 2
fi

# Im Hintergrund starten (Testmodus)
screen -dmS paper-trader bash -c "cd ~/\$DIR && uv run python runner.py --testmodus 2>&1 | tee logs/runner.log"

echo ""
echo "=== Fertig! Bot laeuft im Hintergrund (Testmodus) ==="
echo ""
echo "Status pruefen:"
echo "  ssh $VM 'cd $DIR && uv run python status.py'"
echo ""
echo "Logs live:"
echo "  ssh $VM 'tail -f $DIR/logs/runner.log'"
echo ""
echo "Vollmodus starten (wenn Testmodus OK):"
echo "  ssh $VM 'screen -S paper-trader -X quit; cd $DIR && screen -dmS paper-trader bash -c \"uv run python runner.py 2>&1 | tee logs/runner.log\"'"
EOF

echo ""
echo "=== Deployment abgeschlossen ==="
echo ""
echo "Status direkt von hier:"
echo "  ssh $VM 'cd $DIR && uv run python status.py'"
