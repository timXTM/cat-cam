import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path("/home/pi/catcam_data/catcam_stats.db")
MONTHLY_API_LIMIT = 900


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def initialize():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                trigger_source TEXT NOT NULL,
                motion_percent REAL,
                folder TEXT,
                photo_count INTEGER DEFAULT 0,
                classification TEXT DEFAULT 'pending',
                bird_photo_count INTEGER DEFAULT 0,
                discord_sent INTEGER DEFAULT 0,
                deleted INTEGER DEFAULT 0,
                deleted_at TEXT,
                error TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_usage (
                month TEXT PRIMARY KEY,
                requests INTEGER NOT NULL DEFAULT 0
            )
        """)


def record_trigger(trigger_source, motion_percent, folder):
    timestamp = datetime.now(timezone.utc).isoformat()

    with connect() as conn:
        cursor = conn.execute("""
            INSERT INTO events
            (timestamp, trigger_source, motion_percent, folder)
            VALUES (?, ?, ?, ?)
        """, (
            timestamp,
            trigger_source,
            motion_percent,
            str(folder)
        ))

        return cursor.lastrowid


def update_event(event_id, **fields):
    allowed = {
        "photo_count",
        "classification",
        "bird_photo_count",
        "discord_sent",
        "deleted",
        "deleted_at",
        "error"
    }

    fields = {k: v for k, v in fields.items() if k in allowed}

    if not fields:
        return

    assignments = ", ".join(f"{key} = ?" for key in fields)

    with connect() as conn:
        conn.execute(
            f"UPDATE events SET {assignments} WHERE id = ?",
            list(fields.values()) + [event_id]
        )


def current_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_api_usage():
    with connect() as conn:
        row = conn.execute("""
            SELECT requests FROM api_usage WHERE month = ?
        """, (current_month(),)).fetchone()

    return row[0] if row else 0


def reserve_api_request():
    month = current_month()

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")

        conn.execute("""
            INSERT OR IGNORE INTO api_usage (month, requests)
            VALUES (?, 0)
        """, (month,))

        cursor = conn.execute("""
            UPDATE api_usage
            SET requests = requests + 1
            WHERE month = ? AND requests < ?
        """, (month, MONTHLY_API_LIMIT))

        return cursor.rowcount == 1


def get_statistics():
    with connect() as conn:
        rows = conn.execute("""
            SELECT
                trigger_source,
                classification,
                discord_sent,
                deleted
            FROM events
        """).fetchall()

    stats = {
        "total_triggers": len(rows),
        "motion_triggers": 0,
        "manual_triggers": 0,
        "bird_bursts": 0,
        "no_bird_bursts": 0,
        "pending_bursts": 0,
        "discord_notifications": 0,
        "deleted_bursts": 0,
        "api_requests": get_api_usage(),
        "api_limit": MONTHLY_API_LIMIT
    }

    for source, classification, discord, deleted in rows:
        if source == "motion":
            stats["motion_triggers"] += 1
        elif source == "manual":
            stats["manual_triggers"] += 1

        if classification == "bird":
            stats["bird_bursts"] += 1
        elif classification == "no_bird":
            stats["no_bird_bursts"] += 1
        else:
            stats["pending_bursts"] += 1

        stats["discord_notifications"] += discord
        stats["deleted_bursts"] += deleted

    return stats


initialize()
