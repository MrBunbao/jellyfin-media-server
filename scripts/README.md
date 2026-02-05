# YAMS Audit Scripts

Health audit tools for the YAMS media server stack. These scripts validate Jellyfin library integrity, metadata accuracy, and naming compliance.

## Scripts

| Script | Description |
|--------|-------------|
| `audit.py` | Full audit orchestrator — runs all scanners and produces a combined report |
| `scheduled_audit.py` | Scheduled runner — executes the full audit on a cron schedule with timestamped reports |
| `naming_scanner.py` | File naming compliance scanner (TRaSH Guide conventions) |
| `metadata_checker.py` | Jellyfin ↔ Sonarr/Radarr metadata accuracy checker |
| `library_health_checker.py` | Library health checker (orphans, duplicates, missing metadata) |
| `leaving_soon_checker.py` | Janitorr "Leaving Soon" consistency checker |
| `fix_metadata.py` | Fix metadata mismatches between Jellyfin and Sonarr/Radarr |
| `fix_library.py` | Clean up orphaned and duplicate Jellyfin entries |
| `fix_leaving_soon.py` | Fix Janitorr Leaving Soon false positives |
| `setup-uptime-kuma.py` | Configure Uptime Kuma monitors for YAMS containers (US-008) |
| `setup-uptime-kuma-notifications.py` | Configure Discord notifications in Uptime Kuma (US-009) |
| `setup-uptime-kuma-telegram-notifications.py` | Configure Telegram notifications in Uptime Kuma (US-010) |
| `test-discord-webhook.sh` | Test Discord webhook connectivity (US-005) |
| `test-telegram-webhook.sh` | Test Telegram bot connectivity (US-006) |

## Scheduled Health Check

The `scheduled_audit.py` script runs the full audit on a configurable schedule and is designed to run as a Docker service within the YAMS stack.

### Enabling the Scheduled Check

The `yams-healthcheck` service is defined in `docker-compose.yaml`. To start it:

```bash
docker compose up -d yams-healthcheck
```

To build (or rebuild) the image first:

```bash
docker compose build yams-healthcheck
docker compose up -d yams-healthcheck
```

### Configuration

All settings are controlled via environment variables (set in `.env` or `docker-compose.yaml`):

| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_SCHEDULE` | `0 3 * * 0` | Cron expression for when to run (default: Sunday 03:00) |
| `AUDIT_WEBHOOK_URL` | *(empty)* | Optional webhook URL for summary notifications (Discord/Slack) |
| `AUDIT_RUN_ON_START` | `true` | Run the audit immediately when the container starts |
| `AUDIT_REPORT_DIR` | `/reports` | Report output directory inside the container |
| `AUDIT_MEDIA_ROOT` | `/data/media` | Media root path inside the container |
| `AUDIT_JANITORR_CFG` | `/app/config/janitorr/application.yml` | Janitorr config path |

API credentials (`JELLYFIN_API_KEY`, `SONARR_APIKEY`, `RADARR_APIKEY`) are inherited from the main `.env` file.

### Schedule Examples

| Schedule | Cron Expression |
|----------|----------------|
| Every Sunday at 03:00 (default) | `0 3 * * 0` |
| Daily at midnight | `0 0 * * *` |
| Every 6 hours | `0 */6 * * *` |
| Monday and Friday at 09:00 | `0 9 * * 1,5` |
| First day of month at 02:00 | `0 2 1 * *` |

### Reports

Timestamped reports are saved to `tests/reports/` (mounted from the host):

```
tests/reports/
├── 2026-01-28_030000_full-audit.md   # Timestamped report
├── 2026-02-04_030000_full-audit.md   # Next week's report
├── full-audit.md                      # Always the latest run
└── naming-compliance.md               # From manual scanner runs
```

### Webhook Notifications

Set `AUDIT_WEBHOOK_URL` to a Discord or Slack-compatible webhook URL to receive audit summaries:

```env
AUDIT_WEBHOOK_URL=https://discord.com/api/webhooks/your-webhook-url
```

The notification includes:
- Overall status (ALL CLEAR or ISSUES FOUND)
- Total issue count
- Breakdown by category (naming, metadata, orphans, duplicates, etc.)

### Health Check

The container includes a Docker health check that reports the status of the last audit run. Use `docker inspect` to check:

```bash
docker inspect --format='{{.State.Health.Status}}' yams-healthcheck
```

- **healthy**: Last audit completed without scanner errors
- **unhealthy**: Last audit had scanner errors (e.g., API connection failures)

### Running Manually

Run a one-off audit without the scheduler:

```bash
# Via Docker
docker exec yams-healthcheck python3 scripts/scheduled_audit.py --once

# Directly (from the yams directory)
python3 scripts/scheduled_audit.py --once
```

### Viewing Logs

```bash
docker logs yams-healthcheck           # Full log history
docker logs yams-healthcheck --tail 50 # Last 50 lines
docker logs yams-healthcheck -f        # Follow live
```

## Uptime Kuma Setup

Uptime Kuma provides container monitoring with Discord notifications for the YAMS media stack.

### Initial Monitor Setup (US-008)

The `setup-uptime-kuma.py` script configures Docker container monitors:

```bash
# First time setup (creates admin account and monitors):
python3 scripts/setup-uptime-kuma.py --setup --username admin --password <password>

# Add monitors to existing Uptime Kuma:
python3 scripts/setup-uptime-kuma.py --username admin --password <password>

# Include additional YAMS containers:
python3 scripts/setup-uptime-kuma.py --username admin --password <password> --all
```

### Discord Notification Setup (US-009)

The `setup-uptime-kuma-notifications.py` script configures Discord alerts:

```bash
# Using environment variables (recommended):
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
export UPTIME_KUMA_USERNAME="admin"
export UPTIME_KUMA_PASSWORD="your-password"
python3 scripts/setup-uptime-kuma-notifications.py

# Or provide all arguments directly:
python3 scripts/setup-uptime-kuma-notifications.py \
    --username admin \
    --password <password> \
    --webhook-url "https://discord.com/api/webhooks/..."
```

The script will:
1. Create a "Discord Alerts" notification provider
2. Configure it with `@here` prefix for visibility
3. Assign the notification to all existing monitors
4. Set it as the default for new monitors

### Notification Content

Discord alerts include:
- **Container name**: Which service went down
- **Status**: DOWN or UP (recovered)
- **Downtime duration**: How long the service was unavailable

### Testing Webhook

Before configuring Uptime Kuma, test your webhook:

```bash
./scripts/test-discord-webhook.sh "https://discord.com/api/webhooks/..."
```

### Telegram Notification Setup (US-010)

The `setup-uptime-kuma-telegram-notifications.py` script configures Telegram alerts as a redundant notification channel:

```bash
# Using environment variables (recommended):
export TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
export TELEGRAM_CHAT_ID="123456789"
export UPTIME_KUMA_USERNAME="admin"
export UPTIME_KUMA_PASSWORD="your-password"
python3 scripts/setup-uptime-kuma-telegram-notifications.py

# Or load from secrets file:
source /volume4/docker-v4/yams/.secrets/telegram.env
python3 scripts/setup-uptime-kuma-telegram-notifications.py

# Or provide all arguments directly:
python3 scripts/setup-uptime-kuma-telegram-notifications.py \
    --username admin \
    --password <password> \
    --bot-token "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ" \
    --chat-id "123456789"
```

The script will:
1. Create a "Telegram Alerts" notification provider
2. Assign the notification to all existing monitors
3. Set it as the default for new monitors

### Testing Telegram Webhook

Before configuring Uptime Kuma, test your Telegram bot:

```bash
./scripts/test-telegram-webhook.sh <bot_token> <chat_id>

# Or using environment variables:
source /volume4/docker-v4/yams/.secrets/telegram.env
./scripts/test-telegram-webhook.sh
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DISCORD_WEBHOOK_URL` | Discord webhook URL for alerts |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Telegram chat ID (negative for groups) |
| `UPTIME_KUMA_URL` | Uptime Kuma URL (default: http://localhost:3001) |
| `UPTIME_KUMA_USERNAME` | Admin username |
| `UPTIME_KUMA_PASSWORD` | Admin password |
