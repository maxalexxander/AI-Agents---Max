# Skyro Slack Monitor

Hourly service that scans your Skyro Digital Slack workspace for messages requiring your personal attention, classifies them with Claude, and sends a batched WhatsApp notification via Twilio.

Also supports an on-demand `/slack-scan` command that prints a 24-hour report to your terminal without touching the notification system.

---

## How It Works

On each hourly run it:
1. Fetches the past hour of messages from your DMs, group DMs, `#project-managers`, and any @mentions of you in any channel
2. Runs each message through Claude (`claude-sonnet-4-20250514`) to classify as URGENT or NOT_URGENT
3. VIP contacts (Anastasia, Maria, Taneal, Bianca) are flagged as VIPs in the prompt but still go through the same classifier
4. Batches all urgent messages into a single WhatsApp notification
5. Uses SQLite to ensure no message triggers a notification twice

---

## Setup

### 1. Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it (e.g. "Skyro Monitor"), select your Skyro Digital workspace
3. In the left sidebar go to **OAuth & Permissions**
4. Scroll to **User Token Scopes** (NOT Bot Token Scopes — the bot scopes won't work for reading your own DMs)
5. Add these scopes:
   - `channels:history`
   - `groups:history`
   - `im:history`
   - `mpim:history`
   - `search:read`
   - `users:read`
6. Scroll up and click **Install to Workspace** → Authorize
7. Copy the **User OAuth Token** — it starts with `xoxp-`

> **Important:** Use the User OAuth Token, not the Bot User OAuth Token. The `xoxp-` token reads messages as you; the `xoxb-` bot token can only read messages sent to the bot itself.

### 2. Add the Bot to #project-managers

Since the script needs to read `#project-managers`, you need to be a member (you likely already are). If the channel is private, make sure your Slack account has access.

### 3. Set Up Twilio WhatsApp

**Sandbox (for testing):**
1. Log in to [console.twilio.com](https://console.twilio.com)
2. Go to **Messaging → Try it out → Send a WhatsApp message**
3. Follow the instructions to join the sandbox by texting `join <your-code>` to the Twilio number from your WhatsApp
4. `TWILIO_WHATSAPP_FROM` = `whatsapp:+14155238886` (Twilio sandbox number)
5. `TWILIO_WHATSAPP_TO` = your number in E.164 format, e.g. `whatsapp:+12125551234`

**Moving to production:**
1. Go to **Messaging → Senders → WhatsApp senders** in the Twilio console
2. Submit your business for WhatsApp approval (takes 1–7 days)
3. Once approved, update `TWILIO_WHATSAPP_FROM` to your approved WhatsApp number

### 4. Local Testing

```bash
cd slack-monitor
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env with your credentials (see below)
python main.py          # runs the 1-hour scan + WhatsApp
python main.py --report # prints a 24-hour report, no WhatsApp
```

**.env file:**
```
SLACK_BOT_TOKEN=xoxp-...
ANTHROPIC_API_KEY=sk-ant-...
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_WHATSAPP_TO=whatsapp:+1XXXXXXXXXX
```

### 5. Deploy to Railway

1. Install the Railway CLI: `npm install -g @railway/cli`
2. From the `slack-monitor/` directory:
   ```bash
   railway login
   railway init
   railway up
   ```
3. In the Railway dashboard, go to your project → **Variables** and add all 6 environment variables
4. Railway will detect `railway.toml` and run the script as a cron job every hour

> The `vip_cache.json` and `slack_state.db` files are written to the Railway container's filesystem. They persist within a deployment but reset on re-deploy. This is fine — VIP IDs are re-fetched on first run and dedup state only needs to persist between hourly runs, not across deploys.

---

## Environment Variables

| Variable | Description |
|---|---|
| `SLACK_BOT_TOKEN` | User OAuth Token (`xoxp-...`) from Slack app OAuth & Permissions |
| `ANTHROPIC_API_KEY` | Anthropic API key from console.anthropic.com |
| `TWILIO_ACCOUNT_SID` | Found on your Twilio console dashboard |
| `TWILIO_AUTH_TOKEN` | Found on your Twilio console dashboard |
| `TWILIO_WHATSAPP_FROM` | Twilio WhatsApp sender, e.g. `whatsapp:+14155238886` |
| `TWILIO_WHATSAPP_TO` | Your WhatsApp number, e.g. `whatsapp:+12125551234` |

---

## Troubleshooting

**"missing_scope" error from Slack**
→ You added the scope to Bot Token Scopes instead of User Token Scopes. Go to OAuth & Permissions, scroll to User Token Scopes, add the scope, and reinstall the app.

**"not_in_channel" error**
→ Your Slack account isn't a member of `#project-managers`. Join the channel in Slack and re-run.

**WhatsApp message not received**
→ Make sure you joined the Twilio sandbox by texting the join code first. The sandbox requires this opt-in step.

**VIP names not resolving**
→ The script matches by `display_name` or `real_name` exactly. If Anastasia's Slack display name is "Anastasia K." it won't match "Anastasia". Check the output logs and update `VIP_NAMES` in `state.py` with the exact name as shown in Slack.

**search:read scope errors**
→ This scope only works with a User Token. Confirm your `SLACK_BOT_TOKEN` starts with `xoxp-`, not `xoxb-`.
