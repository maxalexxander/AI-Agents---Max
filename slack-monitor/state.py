"""SQLite-backed deduplication and JSON-backed VIP cache."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "slack_state.db"
VIP_CACHE_PATH = Path(__file__).parent / "vip_cache.json"

# The display names we want to track as VIPs.
VIP_NAMES = ["Anastasia", "Maria Sinicina", "Taneal", "Bianca Franzsen"]


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS seen_messages "
            "(channel_id TEXT, ts TEXT, PRIMARY KEY (channel_id, ts))"
        )


def is_seen(channel_id: str, ts: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_messages WHERE channel_id=? AND ts=?",
            (channel_id, ts),
        ).fetchone()
    return row is not None


def mark_seen(channel_id: str, ts: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_messages (channel_id, ts) VALUES (?, ?)",
            (channel_id, ts),
        )


def load_vip_cache() -> dict:
    """Return {display_name: user_id} for cached VIPs."""
    if VIP_CACHE_PATH.exists():
        with open(VIP_CACHE_PATH) as f:
            return json.load(f)
    return {}


def save_vip_cache(cache: dict):
    with open(VIP_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)
