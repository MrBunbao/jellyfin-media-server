#!/usr/bin/env python3
"""
Setup Discord notifications in Uptime Kuma for YAMS media stack (US-009).

This script configures Discord webhook notifications in Uptime Kuma and assigns
them to all container monitors for immediate alerting when containers go down.

Usage:
    # Configure Discord notifications using webhook URL from environment:
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
    python3 setup-uptime-kuma-notifications.py --username admin --password <password>

    # Or provide webhook URL directly:
    python3 setup-uptime-kuma-notifications.py --username admin --password <password> \
        --webhook-url "https://discord.com/api/webhooks/..."

Requirements:
    pip install uptime-kuma-api
"""

import argparse
import os
import sys

try:
    from uptime_kuma_api import UptimeKumaApi, NotificationType
except ImportError:
    print("Error: uptime-kuma-api is required. Install with: pip install uptime-kuma-api")
    sys.exit(1)


def setup_discord_notifications(url: str, username: str, password: str, webhook_url: str):
    """Set up Discord notifications in Uptime Kuma and assign to all monitors."""

    print("\n=== Uptime Kuma Discord Notification Setup (US-009) ===\n")
    print(f"Connecting to {url}...")

    with UptimeKumaApi(url) as api:
        # Login
        print(f"Logging in as '{username}'...")
        api.login(username, password)
        print("Login successful!")

        # Get existing notifications to check for duplicates
        existing_notifications = api.get_notifications()
        discord_notification_id = None

        for notif in existing_notifications:
            if notif.get('name') == 'Discord Alerts':
                discord_notification_id = notif['id']
                print(f"\nFound existing Discord notification (ID: {discord_notification_id})")
                break

        # Create or update Discord notification
        if discord_notification_id:
            print("Updating existing Discord notification...")
            api.edit_notification(
                id_=discord_notification_id,
                name="Discord Alerts",
                type=NotificationType.DISCORD,
                isDefault=True,
                applyExisting=True,
                discordWebhookUrl=webhook_url,
                discordUsername="Uptime Kuma",
                discordPrefixMessage="@here"  # Mention for visibility
            )
            print("  Updated Discord notification configuration")
        else:
            print("\nCreating Discord notification provider...")
            result = api.add_notification(
                name="Discord Alerts",
                type=NotificationType.DISCORD,
                isDefault=True,
                applyExisting=True,
                discordWebhookUrl=webhook_url,
                discordUsername="Uptime Kuma",
                discordPrefixMessage="@here"  # Mention for visibility
            )
            discord_notification_id = result['id']
            print(f"  Created Discord notification (ID: {discord_notification_id})")

        # Get all monitors and assign notification
        print("\nAssigning Discord notification to all monitors...")
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
                if discord_notification_id in current_notifications:
                    print(f"  Skipping '{monitor_name}' (notification already assigned)")
                    assigned_count += 1
                    continue

                # Add notification to monitor's notification list
                notification_list = dict(current_notifications)
                notification_list[discord_notification_id] = True

                api.edit_monitor(
                    id_=monitor_id,
                    notificationIDList=notification_list
                )
                print(f"  Assigned notification to: {monitor_name}")
                assigned_count += 1
            except Exception as e:
                print(f"  Warning: Could not assign to '{monitor_name}': {e}")

        print(f"\n=== Setup complete: {assigned_count} monitors configured ===")
        print("\nDiscord notification settings:")
        print(f"  - Name: Discord Alerts")
        print(f"  - Default for new monitors: Yes")
        print(f"  - Prefix message: @here (mentions channel)")
        print(f"\nNotification will include:")
        print(f"  - Container name")
        print(f"  - Status (DOWN/UP)")
        print(f"  - Downtime duration")
        print(f"\nAccess the dashboard at: {url}")

        return True


def main():
    parser = argparse.ArgumentParser(
        description="Set up Discord notifications in Uptime Kuma for YAMS media stack"
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
        "--webhook-url",
        default=os.environ.get("DISCORD_WEBHOOK_URL"),
        help="Discord webhook URL (or DISCORD_WEBHOOK_URL env)"
    )
    args = parser.parse_args()

    # Validate required arguments
    if not args.username:
        print("Error: --username is required (or set UPTIME_KUMA_USERNAME)")
        sys.exit(1)
    if not args.password:
        print("Error: --password is required (or set UPTIME_KUMA_PASSWORD)")
        sys.exit(1)
    if not args.webhook_url:
        print("Error: --webhook-url is required (or set DISCORD_WEBHOOK_URL)")
        print("Get webhook URL from: Discord Server Settings > Integrations > Webhooks")
        sys.exit(1)

    # Validate webhook URL format
    if not args.webhook_url.startswith("https://discord.com/api/webhooks/") and \
       not args.webhook_url.startswith("https://discordapp.com/api/webhooks/"):
        print("Error: Invalid Discord webhook URL format")
        print("Expected: https://discord.com/api/webhooks/WEBHOOK_ID/WEBHOOK_TOKEN")
        sys.exit(1)

    try:
        success = setup_discord_notifications(
            args.url,
            args.username,
            args.password,
            args.webhook_url
        )
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
