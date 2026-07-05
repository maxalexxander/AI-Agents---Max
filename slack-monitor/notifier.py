"""Twilio WhatsApp notifications."""

import os
from twilio.rest import Client


def send_whatsapp(urgent_items: list[dict]):
    """
    urgent_items: list of dicts with keys sender, channel, text, reason, time
    Batches all items into a single WhatsApp message.
    """
    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    from_ = os.environ["TWILIO_SMS_FROM"]
    to = os.environ["TWILIO_SMS_TO"]

    count = len(urgent_items)
    lines = [f"🔔 Skyro Alert ({count} urgent)\n"]

    for i, item in enumerate(urgent_items, 1):
        preview = item["text"][:200].replace("\n", " ")
        block = (
            f"{i}. From: {item['sender']} in {item['channel']}\n"
            f"{preview}\n"
            f"Reason: {item['reason']}\n"
            f"Time: {item['time']}"
        )
        lines.append(block)

    body = "\n\n".join(lines)

    client = Client(account_sid, auth_token)
    message = client.messages.create(from_=from_, to=to, body=body)
    print(f"WhatsApp sent: {message.sid}")
