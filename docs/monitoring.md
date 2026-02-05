# YAMS Monitoring Architecture Documentation

This document provides comprehensive documentation of the monitoring setup for the YAMS (Yet Another Media Server) stack running on the Synology NAS.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [VPS Connection Details](#vps-connection-details)
- [Tailscale Setup](#tailscale-setup)
- [Uptime Kuma Configuration](#uptime-kuma-configuration)
- [Webhook Configuration](#webhook-configuration)
- [Adding New Containers to Monitoring](#adding-new-containers-to-monitoring)
- [Memory Limit Recommendations](#memory-limit-recommendations)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

The monitoring infrastructure consists of three layers:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MONITORING LAYERS                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────┐   ┌──────────────────┐   ┌─────────────────┐  │
│  │   Uptime Kuma    │   │  YAMS Monitor    │   │ Health Check    │  │
│  │   (VPS-hosted)   │   │    Daemon        │   │   Scheduler     │  │
│  │   Port 3001      │   │   Port 8087      │   │  (Cron-based)   │  │
│  └────────┬─────────┘   └────────┬─────────┘   └────────┬────────┘  │
│           │                      │                       │           │
│           │ Tailscale            │ Local                 │ Local     │
│           │ Network              │ Docker                │ Docker    │
│           ▼                      ▼                       ▼           │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Docker Engine (NAS)                        │   │
│  │                    41 Containers                              │   │
│  │                    Network: yams_network (172.60.0.0/24)      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Monitoring Components

| Component | Location | Port | Purpose |
|-----------|----------|------|---------|
| Uptime Kuma | VPS | 3001 | External container monitoring with status pages |
| YAMS Monitor Daemon | NAS | 8087 | Continuous async health checks |
| Health Check Scheduler | NAS | N/A | Weekly full library audits |
| Jellystat | NAS | 3033 | Jellyfin-specific analytics |

---

## VPS Connection Details

### Network Configuration

| Device | Tailscale IP | Role |
|--------|--------------|------|
| VPS (Uptime Kuma) | 100.67.114.27 | External monitoring host |
| NAS (Docker Host) | 100.107.222.83 | Container runtime |

### Docker Daemon Access

The Docker daemon is exposed **only** on the Tailscale interface for security:

```
Docker API: tcp://100.107.222.83:2375
```

**Security Note**: The Docker daemon is NOT exposed on:
- LAN interface (10.10.10.10)
- Public interfaces

This ensures only Tailscale-authenticated devices can access the Docker API.

---

## Tailscale Setup

### Overview

Tailscale provides a secure WireGuard-based mesh network connecting the VPS and NAS, enabling:
- Encrypted remote Docker API access
- Uptime Kuma to monitor NAS containers from VPS
- No port forwarding or firewall rules needed

### DNS Configuration

The YAMS stack uses Tailscale MagicDNS with fallback:

```yaml
# In docker-compose.yaml
dns:
  - 100.100.100.100  # Tailscale MagicDNS
  - 8.8.8.8          # Google DNS fallback
```

### Connecting Uptime Kuma to Docker

Uptime Kuma on the VPS connects to the NAS Docker daemon via Tailscale:

1. **Docker Host Configuration** in Uptime Kuma:
   - Host: `100.107.222.83`
   - Port: `2375`
   - Protocol: TCP (plain, not TLS - secured by Tailscale tunnel)

2. **Monitor Type**: Docker Container
3. **Container Selector**: By container name

For detailed setup instructions, see: `/volume4/docker-v4/yams/docs/uptime-kuma-docker-connection.md`

---

## Uptime Kuma Configuration

### Location

- **Database**: `/volume4/docker-v4/yams/config/uptime-kuma/kuma.db`
- **Web UI**: http://100.67.114.27:3001 (via Tailscale)

### Default Monitor Settings

| Setting | Value |
|---------|-------|
| Check Interval | 60 seconds |
| Retry Count | 3 |
| Retry Interval | 60 seconds |
| Monitor Group | "Media Stack" |

### Monitored Containers

**Core Services (11 containers):**
- jellyfin, jellyseerr, sonarr, sonarr-anime
- radarr, radarr-anime, bazarr, prowlarr
- qbittorrent, gluetun, flaresolverr

**Extended Services (with `--all` flag, 8 additional):**
- lidarr, readarr, whisparr, sabnzbd
- tdarr, subgen, recyclarr, jellystat

### Setup Scripts

Located in `/volume4/docker-v4/yams/scripts/`:

| Script | Purpose |
|--------|---------|
| `setup-uptime-kuma.py` | Initial monitor configuration |
| `setup-uptime-kuma-notifications.py` | Discord alert setup |
| `setup-uptime-kuma-telegram-notifications.py` | Telegram alert setup |

---

## Webhook Configuration

### Secrets Location

**IMPORTANT**: Webhook URLs and tokens are stored in environment files that are git-ignored:

| Service | Secrets File | Environment Variables |
|---------|--------------|----------------------|
| Discord | `/volume4/docker-v4/yams/.env` | `DISCORD_WEBHOOK_URL`, `AUDIT_WEBHOOK_URL` |
| Telegram | `/volume4/docker-v4/yams/.secrets/telegram.env` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

### Discord Webhook Setup

1. Create webhook in Discord server (Server Settings → Integrations → Webhooks)
2. Copy webhook URL
3. Add to `.env`:
   ```bash
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/{id}/{token}
   AUDIT_WEBHOOK_URL=https://discord.com/api/webhooks/{id}/{token}
   ```
4. Test connectivity:
   ```bash
   /volume4/docker-v4/yams/scripts/test-discord-webhook.sh
   ```

For detailed instructions: `/volume4/docker-v4/yams/docs/discord-webhook-setup.md`

### Telegram Webhook Setup

1. Create bot via @BotFather, get token
2. Get chat ID from @userinfobot
3. Create secrets file:
   ```bash
   mkdir -p /volume4/docker-v4/yams/.secrets
   cat > /volume4/docker-v4/yams/.secrets/telegram.env << 'EOF'
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   EOF
   chmod 600 /volume4/docker-v4/yams/.secrets/telegram.env
   ```
4. Test connectivity:
   ```bash
   /volume4/docker-v4/yams/scripts/test-telegram-webhook.sh
   ```

### Notification Triggers

Uptime Kuma sends alerts when:
- Container goes DOWN (stops responding)
- Container comes back UP
- Container health check fails 3 consecutive times

---

## Adding New Containers to Monitoring

### Method 1: Automated via Script

Run the setup script with the `--all` flag to add all containers:

```bash
cd /volume4/docker-v4/yams
python3 scripts/setup-uptime-kuma.py --all
```

### Method 2: Manual via Uptime Kuma UI

1. Log into Uptime Kuma at http://100.67.114.27:3001
2. Click "Add New Monitor"
3. Configure:
   - **Monitor Type**: Docker Container
   - **Friendly Name**: Container display name
   - **Docker Host**: Select configured NAS host
   - **Container Name/ID**: Exact container name from docker-compose
   - **Heartbeat Interval**: 60 seconds (recommended)
   - **Retries**: 3
4. Assign to "Media Stack" group
5. Enable notifications (Discord/Telegram)
6. Save

### Method 3: Add to Setup Script

Edit `/volume4/docker-v4/yams/scripts/setup-uptime-kuma.py`:

```python
# Add to CONTAINERS list
CONTAINERS = [
    # ... existing containers ...
    "your-new-container",
]
```

Then run the script to update monitors.

---

## Memory Limit Recommendations

### Current Container Limits

Containers **with** memory limits configured:

| Container | Memory Limit | Memory Reservation |
|-----------|-------------|-------------------|
| jellyfin | 4GB | 512MB |
| jellyseerr | 1GB | 256MB |
| sonarr | 1GB | 256MB |
| sonarr-anime | 1GB | 256MB |
| radarr | 1GB | 256MB |
| radarr-anime | 1GB | 256MB |
| qbittorrent | 1GB | 256MB |
| bazarr | 512MB | 128MB |
| prowlarr | 512MB | 128MB |
| gluetun | 512MB | 128MB |
| jellystat | 512MB | 128MB |
| jellystat-db | 512MB | 128MB |

### Recommended Limits for Common Services

When adding new containers, use these guidelines:

| Container Type | Recommended Limit | Reservation |
|---------------|-------------------|-------------|
| **Media Server** (Jellyfin/Plex) | 4-8GB | 512MB-1GB |
| **Transcoding** (Tdarr, Handbrake) | 4-8GB | 1GB |
| **AI/ML** (Subgen/Whisper) | 8-16GB | 2GB |
| ***arr Apps** (Sonarr, Radarr, etc.) | 1GB | 256MB |
| **Download Clients** (qBittorrent, SABnzbd) | 1-2GB | 256MB |
| **Databases** (PostgreSQL, MariaDB) | 512MB-1GB | 128MB |
| **Utility Services** (Flaresolverr, etc.) | 512MB | 128MB |
| **Search Indexing** (Meilisearch) | 1-2GB | 256MB |

### Adding Memory Limits

Add to container definition in `docker-compose.yaml`:

```yaml
services:
  your-container:
    image: your-image:tag
    # ... other config ...
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 256M
```

**Note**: Host has 62.57 GiB total memory. Plan limits accordingly to avoid overcommitment.

### High-Risk Containers (Currently Without Limits)

These containers should be prioritized for memory limits:

| Container | Risk Level | Recommendation |
|-----------|-----------|----------------|
| tdarr | HIGH | 4-8GB (transcoding) |
| subgen | HIGH | 8-16GB (Whisper AI) |
| meilisearch | MEDIUM | 1-2GB (indexing) |
| flaresolverr | MEDIUM | 512MB-1GB (browser) |
| sabnzbd | MEDIUM | 1-2GB (extraction) |

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Uptime Kuma Cannot Connect to Docker

**Symptoms**: All container monitors show "Down"

**Causes & Solutions**:

| Cause | Solution |
|-------|----------|
| Tailscale disconnected | Check `tailscale status` on both VPS and NAS |
| Docker daemon not listening | Verify: `ss -tlnp | grep 2375` on NAS |
| Firewall blocking | Ensure Tailscale interface is allowed |

**Verification Steps**:
```bash
# On VPS
tailscale ping 100.107.222.83

# Test Docker API
curl http://100.107.222.83:2375/version
```

#### 2. Container Shows "Down" But Is Running

**Symptoms**: Uptime Kuma reports down, `docker ps` shows running

**Causes & Solutions**:

| Cause | Solution |
|-------|----------|
| Container name mismatch | Verify exact name matches docker-compose service |
| Health check failing | Check container logs: `docker logs container-name` |
| Resource starvation | Check `docker stats` for memory/CPU |

#### 3. Webhook Notifications Not Sending

**Symptoms**: No Discord/Telegram alerts despite container issues

**Causes & Solutions**:

| Cause | Solution |
|-------|----------|
| Webhook URL invalid | Run test script: `./scripts/test-discord-webhook.sh` |
| Notification not enabled | Check Uptime Kuma → Monitor → Notifications |
| Rate limited | Wait 5 minutes, Discord has rate limits |

#### 4. OOM Kills (Exit Code 137)

**Symptoms**: Container repeatedly exits with code 137

**Causes & Solutions**:

| Cause | Solution |
|-------|----------|
| No memory limit | Add `deploy.resources.limits.memory` |
| Limit too low | Increase memory limit |
| Memory leak | Check for container updates |

**Investigation**:
```bash
# Check container exit reason
docker inspect container-name --format='{{.State.OOMKilled}}'

# View system OOM events
dmesg | grep -i "out of memory"
```

#### 5. YAMS Monitor Daemon Not Responding

**Symptoms**: Port 8087 not responding

**Causes & Solutions**:

```bash
# Check daemon status
docker ps | grep yams-monitor

# View daemon logs
docker logs yams-monitor

# Restart daemon
docker restart yams-monitor
```

#### 6. Scheduled Audits Not Running

**Symptoms**: No new reports in `/volume4/docker-v4/yams/tests/reports/`

**Causes & Solutions**:

```bash
# Check healthcheck container
docker ps | grep yams-healthcheck
docker logs yams-healthcheck

# Manual audit trigger
docker exec yams-healthcheck python /app/scheduled_audit.py
```

### Log Locations

| Component | Log Access |
|-----------|-----------|
| Docker containers | `docker logs <container-name>` |
| Uptime Kuma | Via web UI or `docker logs uptime-kuma` |
| YAMS Monitor | `docker logs yams-monitor` |
| Audit reports | `/volume4/docker-v4/yams/tests/reports/` |

### Health Check Commands

```bash
# Quick status check for all containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Memory usage check
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"

# Network connectivity test
tailscale status

# Docker API test from VPS
curl -s http://100.107.222.83:2375/containers/json | jq '.[].Names'
```

---

## Related Documentation

- `/volume4/docker-v4/yams/docs/uptime-kuma-docker-connection.md` - Tailscale integration details
- `/volume4/docker-v4/yams/docs/discord-webhook-setup.md` - Discord webhook guide
- `/volume4/docker-v4/yams/docs/memory-audit.md` - Memory limit audit report
- `/volume4/docker-v4/yams/scripts/README.md` - Scripts documentation

---

*Last updated: 2026-02-04*
