#!/bin/bash
# Reattach Gluetun-dependent containers after Gluetun restarts or is recreated.
set -u

YAMS_DIR="${YAMS_DIR:-/volume4/docker-v4/yams}"
VPN_CT="${VPN_CT:-gluetun}"
DEPENDENTS="${DEPENDENTS:-qbittorrent prowlarr}"
COOLDOWN_SEC="${COOLDOWN_SEC:-600}"
STATE_FILE="${STATE_FILE:-/tmp/yams-vpn-watchdog.last}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Only act once Gluetun itself is running and healthy
status=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$VPN_CT" 2>/dev/null)
if [ "$status" != "running healthy" ]; then
    log "$VPN_CT is '${status:-missing}'; waiting"
    exit 0
fi
vpn_id=$(docker inspect -f '{{.Id}}' "$VPN_CT")

broken=""
for c in $DEPENDENTS; do
    info=$(docker inspect -f '{{.State.Status}}|{{.HostConfig.NetworkMode}}' "$c" 2>/dev/null)
    if [ -z "$info" ]; then
        reason="missing"
    elif [ "${info%%|*}" != "running" ]; then
        reason="not running"
    elif [ "${info#*|}" != "container:$vpn_id" ]; then
        reason="attached to an old gluetun container"
    elif ! docker exec "$c" sh -c 'ls /sys/class/net' 2>/dev/null | grep -q eth0; then
        reason="no network (stale namespace after gluetun restart)"
    else
        continue
    fi
    log "$c: $reason"
    broken="$broken $c"
done

[ -z "$broken" ] && exit 0

# Don't recreate more than once per cooldown window
now=$(date +%s)
last=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
if [ $((now - last)) -lt "$COOLDOWN_SEC" ]; then
    log "Cooldown active ($((now - last))s since last recreate); skipping"
    exit 0
fi
echo "$now" > "$STATE_FILE"

log "Recreating:$broken"
cd "$YAMS_DIR" || exit 1
docker compose up -d --force-recreate --no-deps $broken
sleep 20
bash "$YAMS_DIR/scripts/update-port.sh" 2>&1 | tail -2
