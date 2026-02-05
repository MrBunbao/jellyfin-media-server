#!/usr/bin/env python3
"""
Setup Uptime Kuma monitors for YAMS media stack (US-008).

This script configures Docker container monitors in Uptime Kuma for all
media stack containers with a 60-second check interval, grouped under
'Media Stack'.

Usage:
    # First time setup (creates admin account and monitors):
    python3 setup-uptime-kuma.py --setup --username admin --password <password>

    # Add monitors to existing Uptime Kuma:
    python3 setup-uptime-kuma.py --username admin --password <password>

    # Include additional YAMS containers:
    python3 setup-uptime-kuma.py --username admin --password <password> --all

Requirements:
    pip install uptime-kuma-api
"""

import argparse
import sys

try:
    from uptime_kuma_api import UptimeKumaApi, MonitorType
except ImportError:
    print("Error: uptime-kuma-api is required. Install with: pip install uptime-kuma-api")
    sys.exit(1)

# Media stack containers to monitor (from acceptance criteria)
MEDIA_CONTAINERS = [
    {"name": "Jellyfin", "container": "jellyfin"},
    {"name": "Jellyseerr", "container": "jellyseerr"},
    {"name": "Jellystat", "container": "jellystat"},
    {"name": "Jellystat DB", "container": "jellystat-db"},
    {"name": "Komga", "container": "komga"},
    {"name": "Sonarr", "container": "sonarr"},
    {"name": "Radarr", "container": "radarr"},
    {"name": "Prowlarr", "container": "prowlarr"},
    {"name": "Bazarr", "container": "bazarr"},
    {"name": "qBittorrent", "container": "qbittorrent"},
    {"name": "Gluetun", "container": "gluetun"},
]

# Additional YAMS containers for comprehensive monitoring
ADDITIONAL_CONTAINERS = [
    {"name": "Sonarr Anime", "container": "sonarr-anime"},
    {"name": "Radarr Anime", "container": "radarr-anime"},
    {"name": "Lidarr", "container": "lidarr"},
    {"name": "Readarr", "container": "readarr"},
    {"name": "SABnzbd", "container": "sabnzbd"},
    {"name": "Tdarr", "container": "tdarr"},
    {"name": "Recyclarr", "container": "recyclarr"},
    {"name": "FlareSolverr", "container": "flaresolverr"},
]


def setup_uptime_kuma(url: str, username: str, password: str, do_setup: bool, include_additional: bool):
    """Set up Uptime Kuma with Docker container monitors for the media stack."""

    print(f"\n=== Uptime Kuma Setup for YAMS Media Stack ===\n")
    print(f"Connecting to {url}...")

    with UptimeKumaApi(url) as api:
        # Check if initial setup is needed
        if api.need_setup():
            if not do_setup:
                print("Uptime Kuma needs initial setup. Run with --setup flag.")
                sys.exit(1)

            print(f"Performing initial setup - creating admin user '{username}'...")
            api.setup(username, password)
            print("Initial setup complete!")
        else:
            print(f"Logging in as '{username}'...")
            api.login(username, password)
            print("Login successful!")

        # Get existing monitors to avoid duplicates
        existing_monitors = {m['name']: m for m in api.get_monitors()}
        print(f"Found {len(existing_monitors)} existing monitors")

        # Add Docker host for container monitoring
        print("\nConfiguring Docker host...")
        docker_hosts = api.get_docker_hosts()
        docker_host_id = None

        for host in docker_hosts:
            if host.get('dockerType') == 'socket':
                docker_host_id = host['id']
                print(f"  Using existing Docker host: {host.get('name')} (ID: {docker_host_id})")
                break

        if not docker_host_id:
            result = api.add_docker_host(
                name="Local Docker",
                dockerType="socket",
                dockerDaemon="/var/run/docker.sock"
            )
            docker_host_id = result['id']
            print(f"  Added Docker host (ID: {docker_host_id})")

        # Create the Media Stack group
        print("\nCreating 'Media Stack' group...")
        group_id = None

        for name, monitor in existing_monitors.items():
            if monitor.get('type') == MonitorType.GROUP and monitor.get('name') == 'Media Stack':
                group_id = monitor['id']
                print(f"  Found existing group (ID: {group_id})")
                break

        if not group_id:
            result = api.add_monitor(
                type=MonitorType.GROUP,
                name="Media Stack"
            )
            group_id = result['monitorID']
            print(f"  Created group (ID: {group_id})")

        # Create monitors for required containers
        print("\nCreating monitors for media containers...")
        success_count = 0
        containers_to_monitor = list(MEDIA_CONTAINERS)

        if include_additional:
            containers_to_monitor.extend(ADDITIONAL_CONTAINERS)

        for container_info in containers_to_monitor:
            name = container_info['name']
            container = container_info['container']

            if name in existing_monitors:
                print(f"  Skipping '{name}' (already exists)")
                success_count += 1
                continue

            try:
                api.add_monitor(
                    type=MonitorType.DOCKER,
                    name=name,
                    docker_container=container,
                    docker_host=docker_host_id,
                    interval=60,
                    retryInterval=60,
                    maxretries=3,
                    parent=group_id
                )
                print(f"  Created: {name} ({container})")
                success_count += 1
            except Exception as e:
                print(f"  Failed to create '{name}': {e}")

        print(f"\n=== Setup complete: {success_count}/{len(containers_to_monitor)} monitors ===")
        print(f"\nAccess the dashboard at: {url}")

        return success_count == len(containers_to_monitor)


def main():
    parser = argparse.ArgumentParser(
        description="Set up Uptime Kuma monitors for YAMS media stack"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:3001",
        help="Uptime Kuma URL (default: http://localhost:3001)",
    )
    parser.add_argument("--username", required=True, help="Uptime Kuma admin username")
    parser.add_argument("--password", required=True, help="Uptime Kuma admin password")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Perform initial setup (create admin account)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include additional YAMS containers beyond acceptance criteria",
    )
    args = parser.parse_args()

    try:
        success = setup_uptime_kuma(
            args.url,
            args.username,
            args.password,
            args.setup,
            args.all
        )
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
