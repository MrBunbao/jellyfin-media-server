#!/usr/bin/env bash
#
# test-telegram-webhook.sh - Test Telegram bot connectivity
#
# Usage: ./test-telegram-webhook.sh [bot_token] [chat_id]
#
# If no arguments are provided, reads from TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
# environment variables or prompts for input.
#
# ============================================================================
# TELEGRAM BOT SETUP (via BotFather)
# ============================================================================
#
# 1. Open Telegram and search for @BotFather
# 2. Start a chat and send: /newbot
# 3. Follow prompts to name your bot (e.g., "My Alert Bot")
# 4. Choose a username ending in 'bot' (e.g., "my_alert_bot")
# 5. BotFather will provide your BOT TOKEN (keep this secret!)
#    Format: 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
#
# To get your CHAT ID:
# 1. Start a chat with your new bot (search for it by username)
# 2. Send any message to the bot
# 3. Visit: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
# 4. Look for "chat":{"id": YOUR_CHAT_ID} in the JSON response
#
# For group chats:
# 1. Add the bot to your group
# 2. Send a message in the group
# 3. Use getUpdates as above - group IDs are negative numbers
#
# ============================================================================
# TOKEN STORAGE (secure, not in git)
# ============================================================================
#
# Store tokens in: /volume4/docker-v4/yams/.secrets/telegram.env
# This file should contain:
#   TELEGRAM_BOT_TOKEN=your_bot_token_here
#   TELEGRAM_CHAT_ID=your_chat_id_here
#
# Ensure proper permissions:
#   chmod 600 /volume4/docker-v4/yams/.secrets/telegram.env
#
# Add to .gitignore:
#   .secrets/
#
# ============================================================================

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

# Load secrets from file if it exists
load_secrets() {
    local secrets_file="/volume4/docker-v4/yams/.secrets/telegram.env"
    if [[ -f "$secrets_file" ]]; then
        log_info "Loading secrets from $secrets_file"
        # shellcheck source=/dev/null
        source "$secrets_file"
    fi
}

# Get bot token from argument, environment, or prompt
get_bot_token() {
    local token=""

    if [[ -n "${1:-}" ]]; then
        token="$1"
    elif [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        token="$TELEGRAM_BOT_TOKEN"
    else
        log_warn "No bot token provided."
        echo -n "Enter Telegram bot token: "
        read -r token
    fi

    echo "$token"
}

# Get chat ID from argument, environment, or prompt
get_chat_id() {
    local chat_id=""

    if [[ -n "${1:-}" ]]; then
        chat_id="$1"
    elif [[ -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        chat_id="$TELEGRAM_CHAT_ID"
    else
        log_warn "No chat ID provided."
        echo -n "Enter Telegram chat ID: "
        read -r chat_id
    fi

    echo "$chat_id"
}

# Validate bot token format
validate_token() {
    local token="$1"

    if [[ -z "$token" ]]; then
        log_error "Bot token is empty"
        return 1
    fi

    # Token format: numbers:alphanumeric string
    if [[ ! "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
        log_error "Invalid bot token format"
        log_error "Expected format: 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
        return 1
    fi

    return 0
}

# Validate chat ID format
validate_chat_id() {
    local chat_id="$1"

    if [[ -z "$chat_id" ]]; then
        log_error "Chat ID is empty"
        return 1
    fi

    # Chat ID can be positive (user) or negative (group)
    if [[ ! "$chat_id" =~ ^-?[0-9]+$ ]]; then
        log_error "Invalid chat ID format"
        log_error "Expected: numeric ID (negative for groups)"
        return 1
    fi

    return 0
}

# Send test message to Telegram
send_test_message() {
    local token="$1"
    local chat_id="$2"
    local hostname
    local timestamp

    hostname=$(hostname 2>/dev/null || echo "unknown")
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local message
    message=$(cat <<EOF
🔔 *Webhook Test*

This is a test message from the container alert system.

*Host:* \`${hostname}\`
*Timestamp:* \`${timestamp}\`
*Status:* ✅ Webhook is working correctly!

_Docker Container Alerts_
EOF
)

    local api_url="https://api.telegram.org/bot${token}/sendMessage"

    log_info "Sending test message to Telegram..."

    local response
    local http_code

    # Send request and capture both response body and HTTP code
    response=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\": \"${chat_id}\", \"text\": $(echo "$message" | jq -Rs .), \"parse_mode\": \"Markdown\"}" \
        "$api_url")

    # Extract HTTP code (last line) and body (everything before)
    http_code=$(echo "$response" | tail -n1)
    response=$(echo "$response" | sed '$d')

    # Check if response indicates success
    local ok_status
    ok_status=$(echo "$response" | jq -r '.ok // false' 2>/dev/null || echo "false")

    if [[ "$http_code" -eq 200 ]] && [[ "$ok_status" == "true" ]]; then
        log_info "Test message sent successfully! (HTTP $http_code)"
        return 0
    else
        log_error "Failed to send test message (HTTP $http_code)"
        if [[ -n "$response" ]]; then
            local error_desc
            error_desc=$(echo "$response" | jq -r '.description // empty' 2>/dev/null || echo "$response")
            log_error "Response: $error_desc"
        fi
        return 1
    fi
}

# Show help for getting chat ID
show_chat_id_help() {
    local token="$1"
    echo
    log_info "To find your chat ID:"
    echo "  1. Start a chat with your bot on Telegram"
    echo "  2. Send any message to the bot"
    echo "  3. Run this command to see your chat ID:"
    echo
    echo "     curl -s 'https://api.telegram.org/bot${token}/getUpdates' | jq '.result[].message.chat.id'"
    echo
}

main() {
    echo "========================================"
    echo "  Telegram Webhook Test"
    echo "========================================"
    echo

    # Load secrets file if available
    load_secrets

    local bot_token
    local chat_id

    bot_token=$(get_bot_token "${1:-}")
    chat_id=$(get_chat_id "${2:-}")

    if ! validate_token "$bot_token"; then
        exit 1
    fi
    log_info "Bot token format is valid"

    if ! validate_chat_id "$chat_id"; then
        show_chat_id_help "$bot_token"
        exit 1
    fi
    log_info "Chat ID format is valid"

    if send_test_message "$bot_token" "$chat_id"; then
        echo
        log_info "Telegram bot is configured correctly!"
        echo
        echo "To use in other scripts, export these variables:"
        echo "  export TELEGRAM_BOT_TOKEN='$bot_token'"
        echo "  export TELEGRAM_CHAT_ID='$chat_id'"
        echo
        echo "Or source the secrets file:"
        echo "  source /volume4/docker-v4/yams/.secrets/telegram.env"
        exit 0
    else
        echo
        log_error "Telegram webhook test failed"
        show_chat_id_help "$bot_token"
        exit 1
    fi
}

main "$@"
