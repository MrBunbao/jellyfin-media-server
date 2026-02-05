#!/usr/bin/env bash
#
# test-discord-webhook.sh - Test Discord webhook connectivity
#
# Usage: ./test-discord-webhook.sh [webhook_url]
#
# If no webhook_url is provided, reads from DISCORD_WEBHOOK_URL environment
# variable or prompts for input.
#

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get webhook URL from argument, environment, or prompt
get_webhook_url() {
    local url=""

    if [[ -n "${1:-}" ]]; then
        url="$1"
    elif [[ -n "${DISCORD_WEBHOOK_URL:-}" ]]; then
        url="$DISCORD_WEBHOOK_URL"
    elif [[ -n "${AUDIT_WEBHOOK_URL:-}" ]]; then
        url="$AUDIT_WEBHOOK_URL"
    else
        log_warn "No webhook URL provided."
        echo -n "Enter Discord webhook URL: "
        read -r url
    fi

    echo "$url"
}

# Validate webhook URL format
validate_url() {
    local url="$1"

    if [[ -z "$url" ]]; then
        log_error "Webhook URL is empty"
        return 1
    fi

    if [[ ! "$url" =~ ^https://discord\.com/api/webhooks/ ]] && \
       [[ ! "$url" =~ ^https://discordapp\.com/api/webhooks/ ]]; then
        log_error "Invalid Discord webhook URL format"
        log_error "Expected: https://discord.com/api/webhooks/ID/TOKEN"
        return 1
    fi

    return 0
}

# Send test message to Discord
send_test_message() {
    local url="$1"
    local hostname
    local timestamp

    hostname=$(hostname 2>/dev/null || echo "unknown")
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local payload
    payload=$(cat <<EOF
{
    "embeds": [{
        "title": "Webhook Test",
        "description": "This is a test message from the container alert system.",
        "color": 3066993,
        "fields": [
            {
                "name": "Host",
                "value": "${hostname}",
                "inline": true
            },
            {
                "name": "Timestamp",
                "value": "${timestamp}",
                "inline": true
            },
            {
                "name": "Status",
                "value": "Webhook is working correctly!",
                "inline": false
            }
        ],
        "footer": {
            "text": "Docker Container Alerts"
        }
    }]
}
EOF
)

    log_info "Sending test message to Discord..."

    local response
    local http_code

    # Send request and capture both response body and HTTP code
    response=$(curl -s -w "\n%{http_code}" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$url")

    # Extract HTTP code (last line) and body (everything before)
    http_code=$(echo "$response" | tail -n1)
    response=$(echo "$response" | sed '$d')

    if [[ "$http_code" -ge 200 ]] && [[ "$http_code" -lt 300 ]]; then
        log_info "Test message sent successfully! (HTTP $http_code)"
        return 0
    else
        log_error "Failed to send test message (HTTP $http_code)"
        if [[ -n "$response" ]]; then
            log_error "Response: $response"
        fi
        return 1
    fi
}

main() {
    echo "========================================"
    echo "  Discord Webhook Test"
    echo "========================================"
    echo

    local webhook_url
    webhook_url=$(get_webhook_url "${1:-}")

    if ! validate_url "$webhook_url"; then
        exit 1
    fi

    log_info "Webhook URL format is valid"

    if send_test_message "$webhook_url"; then
        echo
        log_info "Discord webhook is configured correctly!"
        exit 0
    else
        echo
        log_error "Discord webhook test failed"
        exit 1
    fi
}

main "$@"
