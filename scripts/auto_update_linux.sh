#!/bin/bash
# auto_update_linux.sh — for Raspberry Pi / Linux
# Install: copy to the repo, chmod +x, then add to crontab:
#   */5 * * * * /path/to/computer_monitor/scripts/auto_update_linux.sh

set -euo pipefail

REPO="/home/pi/computer_monitor"   # change to your actual path
LOG="/tmp/monitor-updater.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

cd "$REPO"

git fetch origin main --quiet 2>/dev/null

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    log "No updates ($(git rev-parse --short HEAD))"
    exit 0
fi

log "Update found — pulling..."
git pull origin main --quiet

log "Checking agent dependencies..."
"$REPO/agent/.venv/bin/pip" install --quiet -r "$REPO/agent/requirements.txt"

log "Restarting agent service..."
sudo systemctl restart monitor-agent

log "Done — now at $(git rev-parse --short HEAD)"
