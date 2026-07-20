#!/usr/bin/env python3
"""
Skyro Slack Monitor

Normal mode (hourly cron): scans the past hour for urgent messages and sends
a WhatsApp notification via Twilio if any are found.

Report mode (--report): scans the past 24 hours and prints a plain-text
summary to stdout. Does not send WhatsApp or touch the dedup database.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import certifi
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import classifier
import notifier
import state

# Homebrew's OpenSSL cert bundle can be missing/empty on some machines, which
# breaks SSL verification for the Slack API. Point at certifi's bundle
# (already a dependency via slack_sdk/requests) so this doesn't depend on the
# system having its own CA certs installed.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

load_dotenv(Path(__file__).parent / ".env")

REQUIRED_ENV_BASE = [
    "SLACK_BOT_TOKEN",
    "ANTHROPIC_API_KEY",
]

REQUIRED_ENV_NOTIFY = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_SMS_FROM",
    "TWILIO_SMS_TO",
]


def check_env(report_mode: bool):
    required = REQUIRED_ENV_BASE if report_mode else REQUIRED_ENV_BASE + REQUIRED_ENV_NOTIFY
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Slack API helpers
# ---------------------------------------------------------------------------

def slack_call(fn, *args, **kwargs):
    """Call a Slack SDK method with exponential backoff on rate limits."""
    for attempt in range(4):
        try:
            return fn(*args, **kwargs)
        except SlackApiError as e:
            if e.response.get("error") == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 2 ** attempt))
                print(f"Rate limited — sleeping {retry_after}s")
                time.sleep(retry_after)
            else:
                raise
    raise RuntimeError("Exceeded Slack API retry limit")


def get_my_user_id(client: WebClient) -> str:
    # auth.test returns the user ID of the token owner
    return slack_call(client.auth_test)["user_id"]


def build_vip_cache(client: WebClient) -> dict:
    """
    Load VIP cache from disk. For any VIP name not yet resolved,
    page through users.list to find their user ID by display name or real name.
    """
    cache = state.load_vip_cache()
    missing = [name for name in state.VIP_NAMES if name not in cache]
    if not missing:
        return cache

    print(f"Looking up Slack IDs for: {missing}")
    cursor = None
    while missing:
        kwargs = {"limit": 200}
        if cursor:
            kwargs["cursor"] = cursor
        resp = slack_call(client.users_list, **kwargs)

        for member in resp["members"]:
            if member.get("deleted") or member.get("is_bot"):
                continue
            profile = member.get("profile", {})
            display = profile.get("display_name", "").strip()
            real = profile.get("real_name", "").strip()
            for name in list(missing):
                if name.lower() in (display.lower(), real.lower()):
                    cache[name] = member["id"]
                    missing.remove(name)
                    print(f"  Resolved {name} → {member['id']}")

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    if missing:
        print(f"WARNING: Could not resolve Slack IDs for: {missing}")

    state.save_vip_cache(cache)
    return cache


def resolve_user_name(client: WebClient, user_id: str, name_cache: dict) -> str:
    """Return a human-readable name for a Slack user ID."""
    if user_id in name_cache:
        return name_cache[user_id]
    try:
        resp = slack_call(client.users_info, user=user_id)
        profile = resp["user"]["profile"]
        name = profile.get("display_name") or profile.get("real_name") or user_id
    except SlackApiError:
        name = user_id
    name_cache[user_id] = name
    return name


def get_channel_name(client: WebClient, channel_id: str, channel_cache: dict) -> str:
    if channel_id in channel_cache:
        return channel_cache[channel_id]
    try:
        resp = slack_call(client.conversations_info, channel=channel_id)
        info = resp["channel"]
        # DMs show as the other user's name; named channels have a name field
        name = info.get("name") or "DM"
    except SlackApiError:
        name = channel_id
    channel_cache[channel_id] = name
    return name


def get_thread_context(client: WebClient, channel_id: str, thread_ts: str, msg_ts: str) -> list[str]:
    """
    Fetch up to 3 messages from the thread that preceded this message.
    Returns them as plain strings (oldest first).
    """
    try:
        resp = slack_call(
            client.conversations_replies,
            channel=channel_id,
            ts=thread_ts,
            limit=20,
        )
        messages = resp.get("messages", [])
        # Exclude the message itself; keep only those before it
        prior = [m for m in messages if m["ts"] != msg_ts]
        return [m.get("text", "") for m in prior[-3:]]
    except SlackApiError:
        return []


# ---------------------------------------------------------------------------
# Message collection
# ---------------------------------------------------------------------------

def fetch_all_messages(client: WebClient, report_mode: bool) -> list[dict]:
    """
    Fetch messages from every channel the user is a member of.

    Cron mode: uses a fixed 1-hour lookback window across all channels.
    Report mode: uses each channel's last_read timestamp so only truly
    unread messages are returned.
    """
    cron_oldest = time.time() - 3600
    all_messages = []
    seen_keys: set = set()
    cursor = None

    while True:
        kwargs = {
            "types": "public_channel,private_channel,im,mpim",
            "limit": 200,
            "exclude_archived": True,
        }
        if cursor:
            kwargs["cursor"] = cursor
        resp = slack_call(client.conversations_list, **kwargs)

        for ch in resp.get("channels", []):
            if not ch.get("is_member"):
                continue

            channel_id = ch["id"]

            if report_mode:
                # Skip channels with nothing unread
                if not ch.get("unread_count", 0):
                    continue
                last_read = ch.get("last_read")
                oldest = float(last_read) if last_read else cron_oldest
            else:
                oldest = cron_oldest

            try:
                hist = slack_call(
                    client.conversations_history,
                    channel=channel_id,
                    oldest=str(oldest),
                    limit=100,
                )
            except SlackApiError as e:
                # Skip channels we can't read (e.g. no longer a member)
                print(f"  Skipping {channel_id}: {e.response.get('error')}")
                continue

            for msg in hist.get("messages", []):
                if msg.get("subtype"):  # skip join/leave/bot/system messages
                    continue
                key = (channel_id, msg["ts"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    msg["_channel_id"] = channel_id
                    all_messages.append(msg)

        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return all_messages


def process_messages(
    client: WebClient,
    messages: list[dict],
    vip_cache: dict,
    report_mode: bool,
) -> list[dict]:
    """
    Classify each message. In normal mode, skips already-seen messages and
    marks processed ones as seen. In report mode, classifies everything.
    Returns a list of urgent item dicts.
    """
    vip_ids = set(vip_cache.values())
    name_cache: dict = {}
    channel_cache: dict = {}
    urgent_items = []

    for msg in messages:
        channel_id = msg["_channel_id"]
        ts = msg["ts"]
        user_id = msg.get("user", "")
        text = msg.get("text", "").strip()

        if not text or not user_id:
            continue

        # In normal mode, skip messages we've already notified about
        if not report_mode and state.is_seen(channel_id, ts):
            continue

        sender = resolve_user_name(client, user_id, name_cache)
        channel_name = get_channel_name(client, channel_id, channel_cache)
        thread_ts = msg.get("thread_ts", ts)
        thread_context = get_thread_context(client, channel_id, thread_ts, ts)
        is_vip = user_id in vip_ids

        verdict, reason = classifier.classify(text, sender, thread_context, is_vip=is_vip)
        print(f"  [{verdict}] {sender} in #{channel_name}: {text[:60]}…")

        if not report_mode:
            state.mark_seen(channel_id, ts)

        if verdict == "URGENT":
            msg_time = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%H:%M")
            urgent_items.append({
                "sender": sender,
                "channel": f"#{channel_name}",
                "text": text,
                "reason": reason,
                "time": msg_time,
            })

    return urgent_items


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--report",
        action="store_true",
        help="Scan the past 24h and print a report. No WhatsApp, no DB writes.",
    )
    args = parser.parse_args()

    check_env(report_mode=args.report)

    if not args.report:
        state.init_db()

    client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

    print("Building VIP cache...")
    vip_cache = build_vip_cache(client)

    label = "all unread messages" if args.report else "the past 1 hour"
    print(f"Fetching {label} across all channels...")

    messages = fetch_all_messages(client, report_mode=args.report)
    print(f"  {len(messages)} messages to evaluate")

    urgent_items = process_messages(client, messages, vip_cache, report_mode=args.report)

    if args.report:
        _print_report(urgent_items)
    else:
        if urgent_items:
            print(f"\nSending WhatsApp notification ({len(urgent_items)} urgent)...")
            notifier.send_whatsapp(urgent_items)
        else:
            print("No urgent messages — nothing to send.")


def _print_report(urgent_items: list[dict]):
    now = datetime.now().strftime("%B %d, %Y %H:%M")
    print(f"\n📊 Slack Scan — All Unread Messages ({now})\n")

    if not urgent_items:
        print("✅ No urgent messages found.")
        return

    print(f"⚠️  {len(urgent_items)} urgent message{'s' if len(urgent_items) != 1 else ''}:\n")
    for item in urgent_items:
        preview = item["text"][:120].replace("\n", " ")
        print(f"• {item['sender']} in {item['channel']} — \"{preview}\"")
        print(f"  Reason: {item['reason']}")
        print()


if __name__ == "__main__":
    main()
