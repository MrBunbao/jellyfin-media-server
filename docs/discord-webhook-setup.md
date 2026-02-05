# Discord Webhook Setup for Container Alerts

This guide documents how to create and configure a Discord webhook for receiving container alerts.

## Creating a Discord Webhook

### Step 1: Open Server Settings
1. Open Discord and navigate to the server where you want to receive alerts
2. Click the server name at the top-left to open the dropdown menu
3. Select **Server Settings**

### Step 2: Create the Webhook
1. In the left sidebar, click **Integrations**
2. Click **Webhooks** (or **View Webhooks** if you already have some)
3. Click **New Webhook**
4. Configure the webhook:
   - **Name**: Enter a name like "Container Alerts" or "Docker Alerts"
   - **Channel**: Select the channel where alerts should be posted
   - **Avatar**: (Optional) Upload a custom avatar image
5. Click **Copy Webhook URL** - this is your webhook URL
6. Click **Save Changes**

### Step 3: Secure the Webhook URL
**IMPORTANT**: The webhook URL contains a secret token. Anyone with this URL can post messages to your channel.

- **Never commit the webhook URL to git**
- Store it in environment variables only
- If compromised, delete and recreate the webhook immediately

## Webhook URL Storage

The webhook URL should be stored in `/volume4/docker-v4/yams/.env`:

```bash
# Discord Webhook for Container Alerts
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

This file is excluded from git via `.gitignore`, ensuring the secret URL is not committed to version control.

Alternatively, you can use `AUDIT_WEBHOOK_URL` which is also supported by the container alert system.

## Testing the Webhook

Use the provided test script to verify your webhook is working:

```bash
# Method 1: Pass URL as argument
/volume4/docker-v4/scripts/test-discord-webhook.sh "https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"

# Method 2: Use environment variable
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN"
/volume4/docker-v4/scripts/test-discord-webhook.sh

# Method 3: Source from .env file
source /volume4/docker-v4/yams/.env
/volume4/docker-v4/scripts/test-discord-webhook.sh
```

A successful test will:
1. Validate the webhook URL format
2. Send a test embed message to your Discord channel
3. Display a success or failure message

## Webhook URL Format

Valid Discord webhook URLs follow this pattern:
```
https://discord.com/api/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}
```

or the legacy format:
```
https://discordapp.com/api/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}
```

## Troubleshooting

### "Invalid Discord webhook URL format"
- Ensure you copied the complete URL from Discord
- Check that the URL starts with `https://discord.com/api/webhooks/`

### "Failed to send test message (HTTP 401)"
- The webhook token is invalid or expired
- Delete the webhook in Discord and create a new one

### "Failed to send test message (HTTP 404)"
- The webhook has been deleted
- Create a new webhook in Discord

### No message appears in Discord
- Check you're looking at the correct channel
- Verify the webhook is still active in Server Settings > Integrations > Webhooks
