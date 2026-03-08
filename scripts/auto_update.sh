#!/bin/bash
# auto_update.sh — checks GitHub for new commits and restarts the agent if code changed
# Run by launchd every 5 minutes.

set -euo pipefail

REPO="/Users/Jason/AI/computer_monitor"
AGENT_PLIST="$HOME/Library/LaunchAgents/com.monitor.agent.plist"
LOG="/tmp/monitor-updater.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

cd "$REPO"

# Fetch latest commit hash from origin without changing local files
git fetch origin main --quiet 2>/dev/null

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    log "No updates ($(git rev-parse --short HEAD))"
    exit 0
fi

log "Update found: $LOCAL -> $REMOTE  Pulling..."
git pull origin main --quiet

# Reinstall agent deps in case requirements.txt changed
log "Checking agent dependencies..."
"$REPO/agent/.venv/bin/pip" install --quiet -r "$REPO/agent/requirements.txt"

# Restart the agent launchd job to pick up the new code
log "Restarting agent..."
launchctl unload "$AGENT_PLIST" 2>/dev/null || true
sleep 2
launchctl load "$AGENT_PLIST"

log "Agent restarted successfully with $(git rev-parse --short HEAD)"
