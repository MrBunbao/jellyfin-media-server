#!/usr/bin/env python3
"""
Setup Telegram notifications in Uptime Kuma for YAMS media stack (US-010).

This script configures Telegram bot notifications in Uptime Kuma and assigns
them to all container monitors for redundant alerting when containers go down.

Usage:
    # Configure Telegram notifications using bot token and chat ID from environment:
    export TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
    export TELEGRAM_CHAT_ID="123456789"
    python3 setup-uptime-kuma-telegram-notifications.py --username admin --password <password>

    # Or provide credentials directly:
    python3 setup-uptime-kuma-telegram-notifications.py --username admin --password <password> \
        --bot-token "123456789:ABCdefGHIjklMNOpqrsTUvwxYZ" \
        --chat-id "123456789"

    # Load from secrets file:
    source /volume4/docker-v4/yams/.secrets/telegram.env
    python3 setup-uptime-kuma-telegram-notifications.py --username admin --password <password>

Requirements:
    pip install uptime-kuma-api
"""

import argparse
import os
import re
import sys

try:
    from uptime_kuma_api import UptimeKumaApi, NotificationType
except ImportError:
    print("Error: uptime-kuma-api is required. Install with: pip install uptime-kuma-api")
    sys.exit(1)


def validate_bot_token(token: str) -> bool:
    """Validate Telegram bot token format (123456789:ABCdefGHIjklMNOpqrSTUvwxYZ)."""
    pattern = r'^[0-9]+:[A-Za-z0-9_-]+$'
    return bool(re.match(pattern, token))


def validate_chat_id(chat_id: str) -> bool:
    """Validate Telegram chat ID format (positive for users, negative for groups)."""
    pattern = r'^-?[0-9]+$'
    return bool(re.match(pattern, chat_id))


def setup_telegram_notifications(url: str, username: str, password: str, bot_token: str, chat_id: str):
    """Set up Telegram notifications in Uptime Kuma and assign to all monitors."""

    print("\n=== Uptime Kuma Telegram Notification Setup (US-010) ===\n")
    print(f"Connecting to {url}...")

    with UptimeKumaApi(url) as api:
        # Login
        print(f"Logging in as '{username}'...")
        api.login(username, password)
        print("Login successful!")

        # Get existing notifications to check for duplicates
        existing_notifications = api.get_notifications()
        telegram_notification_id = None

        for notif in existing_notifications:
            if notif.get('name') == 'Telegram Alerts':
                telegram_notification_id = notif['id']
                print(f"\nFound existing Telegram notification (ID: {telegram_notification_id})")
                break

        # Create or update Telegram notification
        if telegram_notification_id:
            print("Updating existing Telegram notification...")
            api.edit_notification(
                id_=telegram_notification_id,
                name="Telegram Alerts",
                type=NotificationType.TELEGRAM,
                isDefault=True,
                applyExisting=True,
                telegramBotToken=bot_token,
                telegramChatID=chat_id,
            )
            print("  Updated Telegram notification configuration")
        else:
            print("\nCreating Telegram notification provider...")
            result = api.add_notification(
                name="Telegram Alerts",
                type=NotificationType.TELEGRAM,
                isDefault=True,
                applyExisting=True,
                telegramBotToken=bot_token,
                telegramChatID=chat_id,
            )
            telegram_notification_id = result['id']
            print(f"  Created Telegram notification (ID: {telegram_notification_id})")

        # Get all monitors and assign notification
        print("\nAssigning Telegram notification to all monitors...")
        monitors = api.get_monitors()
        assigned_count = 0

        for monitor in monitors:
            monitor_id = monitor['id']
            monitor_name = monitor['name']

            # Skip groups (they don't need notifications directly)
            if monitor.get('type') == 'group':
                continue

            try:
                # Get current monitor details to preserve settings
                monitor_details = api.get_monitor(monitor_id)

                # Check if notification already assigned
                current_notifications = monitor_details.get('notificationIDList', {})
                if telegram_notification_id in current_notifications:
                    print(f"  Skipping '{monitor_name}' (notification already assigned)")
                    assigned_count += 1
                    continue

                # Add notification to monitor's notification list
                notification_list = dict(current_notifications)
                notification_list[telegram_notification_id] = True

                api.edit_monitor(
                    id_=monitor_id,
                    notificationIDList=notification_list
                )
                print(f"  Assigned notification to: {monitor_name}")
                assigned_count += 1
            except Exception as e:
                print(f"  Warning: Could not assign to '{monitor_name}': {e}")

        print(f"\n=== Setup complete: {assigned_count} monitors configured ===")
        print("\nTelegram notification settings:")
        print(f"  - Name: Telegram Alerts")
        print(f"  - Default for new monitors: Yes")
        print(f"  - Chat ID: {chat_id}")
        print(f"\nNotification will include:")
        print(f"  - Container name")
        print(f"  - Status (DOWN/UP)")
        print(f"  - Downtime duration")
        print(f"\nAccess the dashboard at: {url}")

        return True


def main():
    parser = argparse.ArgumentParser(
        description="Set up Telegram notifications in Uptime Kuma for YAMS media stack"
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("UPTIME_KUMA_URL", "http://localhost:3001"),
        help="Uptime Kuma URL (default: UPTIME_KUMA_URL env or http://localhost:3001)",
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("UPTIME_KUMA_USERNAME"),
        help="Uptime Kuma admin username (or UPTIME_KUMA_USERNAME env)"
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("UPTIME_KUMA_PASSWORD"),
        help="Uptime Kuma admin password (or UPTIME_KUMA_PASSWORD env)"
    )
    parser.add_argument(
        "--bot-token",
        default=os.environ.get("TELEGRAM_BOT_TOKEN"),
        help="Telegram bot token (or TELEGRAM_BOT_TOKEN env)"
    )
    parser.add_argument(
        "--chat-id",
        default=os.environ.get("TELEGRAM_CHAT_ID"),
        help="Telegram chat ID (or TELEGRAM_CHAT_ID env)"
    )
    args = parser.parse_args()

    # Validate required arguments
    if not args.username:
        print("Error: --username is required (or set UPTIME_KUMA_USERNAME)")
        sys.exit(1)
    if not args.password:
        print("Error: --password is required (or set UPTIME_KUMA_PASSWORD)")
        sys.exit(1)
    if not args.bot_token:
        print("Error: --bot-token is required (or set TELEGRAM_BOT_TOKEN)")
        print("Get bot token from: @BotFather on Telegram")
        sys.exit(1)
    if not args.chat_id:
        print("Error: --chat-id is required (or set TELEGRAM_CHAT_ID)")
        print("Get chat ID from: https://api.telegram.org/bot<TOKEN>/getUpdates")
        sys.exit(1)

    # Validate bot token format
    if not validate_bot_token(args.bot_token):
        print("Error: Invalid Telegram bot token format")
        print("Expected format: 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ")
        sys.exit(1)

    # Validate chat ID format
    if not validate_chat_id(args.chat_id):
        print("Error: Invalid Telegram chat ID format")
        print("Expected: numeric ID (negative for groups)")
        sys.exit(1)

    try:
        success = setup_telegram_notifications(
            args.url,
            args.username,
            args.password,
            args.bot_token,
            args.chat_id
        )
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
