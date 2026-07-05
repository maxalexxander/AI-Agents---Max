#!/usr/bin/env python3
"""Sync Calendly call data to a Notion calendar database."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
import requests
from notion_client import Client as NotionClient
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

import json

load_dotenv(Path(__file__).parent / ".env")

OVERRIDES_PATH = Path(__file__).parent / "email_overrides.json"


def load_email_overrides():
    if OVERRIDES_PATH.exists():
        with open(OVERRIDES_PATH) as f:
            return {k: v.strip().lower() for k, v in json.load(f).items() if v.strip()}
    return {}

CALENDLY_TOKEN = os.environ["CALENDLY_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
_creds_raw = os.environ["GOOGLE_CREDENTIALS_PATH"]
GOOGLE_CREDENTIALS_PATH = str(Path(_creds_raw) if Path(_creds_raw).is_absolute() else Path(__file__).parent / _creds_raw)
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "19gk9nkq4sre5ByAMyp9SqEpptBBk4Z6n5JnfCH-f-B4")

CALENDLY_HEADERS = {"Authorization": f"Bearer {CALENDLY_TOKEN}"}


def read_clients():
    creds = Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=GOOGLE_SHEET_ID, range="A:L")
        .execute()
    )
    rows = result.get("values", [])
    if not rows:
        print("No data found in sheet.")
        sys.exit(1)

    # Detect column indices from header row
    header = [h.strip().lower() for h in rows[0]]
    col = {
        "initials": 0,
        "client": 1,
        "email": 2,
        "cadence": next((i for i, h in enumerate(header) if "cadence" in h), 10),
        "status": next((i for i, h in enumerate(header) if h == "status"), 11),
    }

    clients = []
    seen_emails = set()

    for row in rows[1:]:  # skip header
        if len(row) < 3:
            continue
        initials = row[col["initials"]].strip()
        name = row[col["client"]].strip()
        email = row[col["email"]].strip().lower()
        cadence_str = row[col["cadence"]].strip() if len(row) > col["cadence"] else ""
        status = row[col["status"]].strip() if len(row) > col["status"] else ""

        if "churn" in status.lower():
            continue
        if not email:
            continue
        if email in seen_emails:
            continue
        seen_emails.add(email)

        if "fame on central" in name.lower():
            initials = "FOC"

        try:
            cadence = int(cadence_str)
        except (ValueError, TypeError):
            continue  # no cadence = no scheduled calls, skip

        clients.append({"initials": initials, "name": name, "email": email, "cadence": cadence})

    return clients


def get_calendly_org_uri():
    resp = requests.get("https://api.calendly.com/users/me", headers=CALENDLY_HEADERS)
    resp.raise_for_status()
    return resp.json()["resource"]["current_organization"]


def get_most_recent_past_event(org_uri, email):
    now = datetime.now(timezone.utc)
    resp = requests.get(
        "https://api.calendly.com/scheduled_events",
        headers=CALENDLY_HEADERS,
        params={
            "organization": org_uri,
            "invitee_email": email,
            "sort": "start_time:desc",
            "count": 10,
            "status": "active",
        },
    )
    resp.raise_for_status()
    for event in resp.json().get("collection", []):
        start = datetime.fromisoformat(event["start_time"].replace("Z", "+00:00"))
        if start < now:
            return start
    return None


def format_name(initials, dt):
    """Format: 'PR - 1/7/25' — no leading zeros, 2-digit year."""
    return f"{initials} - {dt.month}/{dt.day}/{str(dt.year)[2:]}"


def get_existing_notion_names():
    notion = NotionClient(auth=NOTION_TOKEN)
    names = set()
    cursor = None
    while True:
        kwargs = {"database_id": NOTION_DATABASE_ID, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.databases.query(**kwargs)
        for page in resp["results"]:
            title_prop = page["properties"].get("Name", {}).get("title", [])
            if title_prop:
                names.add(title_prop[0]["plain_text"])
        if not resp["has_more"]:
            break
        cursor = resp["next_cursor"]
    return names


def create_notion_entry(name, dt):
    notion = NotionClient(auth=NOTION_TOKEN)
    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={
            "Name": {"title": [{"text": {"content": name}}]},
            "Date": {"date": {"start": dt.isoformat()}},
        },
    )


def main():
    print("Reading clients from Google Sheet...")
    clients = read_clients()
    print(f"  {len(clients)} active clients")

    email_overrides = load_email_overrides()
    print(f"  {len(email_overrides)} email override(s) loaded")

    print("Getting Calendly organization...")
    org_uri = get_calendly_org_uri()

    print("Fetching existing Notion entries...")
    existing_names = get_existing_notion_names()
    print(f"  {len(existing_names)} existing entries")

    unmatched = []
    created = 0
    skipped = 0

    for client in clients:
        lookup_email = email_overrides.get(client["name"], client["email"])
        label = f"{lookup_email} [override]" if lookup_email != client["email"] else lookup_email
        print(f"\n{client['name']} ({label}):")
        last_call = get_most_recent_past_event(org_uri, lookup_email)

        if not last_call:
            print("  ! No Calendly event found — email may not match calendar invites")
            unmatched.append(client)
            continue

        next_call = last_call + timedelta(days=client["cadence"])
        pairs = [
            (format_name(client["initials"], last_call), last_call),
            (format_name(client["initials"], next_call), next_call),
        ]

        for name, dt in pairs:
            if name in existing_names:
                print(f"  → Skip (exists): {name}")
                skipped += 1
            else:
                create_notion_entry(name, dt)
                print(f"  → Created: {name}")
                created += 1

    print(f"\n{'─' * 40}")
    print(f"Created: {created}  |  Skipped (already exist): {skipped}")

    if unmatched:
        print(f"\n⚠ No Calendly match for {len(unmatched)} client(s):")
        for c in unmatched:
            print(f"  - {c['name']}  ({c['email']})")
        print("\nThe email in the spreadsheet may not match the one used for calendar invites.")
        print("Update the spreadsheet email and re-run, or check Calendly directly.")


if __name__ == "__main__":
    main()
