#!/bin/sh
# Docker health check for the YAMS scheduled audit container.
# Reads the health status JSON written by scheduled_audit.py and checks:
#   1. The status file exists (at least one audit has run)
#   2. The status field is not reporting scanner errors

HEALTH_FILE="/tmp/yams-audit-health.json"

if [ ! -f "$HEALTH_FILE" ]; then
    # No audit has run yet — report healthy (startup grace period)
    exit 0
fi

# Check the status field
status=$(python3 -c "
import json, sys
try:
    data = json.load(open('$HEALTH_FILE'))
    print(data.get('status', 'unknown'))
except Exception:
    print('error')
")

if [ "$status" = "healthy" ]; then
    exit 0
else
    exit 1
fi
