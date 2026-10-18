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
        "discord_photo_count",
        "discord_status",
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


def initialize_step4():
    """Add photo-level classifications and Discord delivery state."""
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS photo_detections (
                event_id INTEGER NOT NULL,
                photo_path TEXT NOT NULL,
                bird_detected INTEGER NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                labels_json TEXT,
                PRIMARY KEY (event_id, photo_path)
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
        if 'discord_photo_count' not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN discord_photo_count INTEGER DEFAULT 0")
        if 'discord_status' not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN discord_status TEXT DEFAULT 'pending'")


def save_photo_detections(event_id, results):
    """Persist successful per-image classifications, even if a burst is incomplete."""
    import json
    with connect() as conn:
        for result in results:
            conn.execute("""
                INSERT INTO photo_detections
                    (event_id, photo_path, bird_detected, confidence, labels_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id, photo_path) DO UPDATE SET
                    bird_detected=excluded.bird_detected,
                    confidence=excluded.confidence,
                    labels_json=excluded.labels_json
            """, (
                event_id, str(result['photo']), int(result['bird_detected']),
                float(result['bird_confidence']), json.dumps(result['bird_labels'])
            ))


def get_bird_photos(event_id):
    with connect() as conn:
        rows = conn.execute("""
            SELECT photo_path FROM photo_detections
            WHERE event_id = ? AND bird_detected = 1
            ORDER BY photo_path
        """, (event_id,)).fetchall()
    return [Path(row[0]) for row in rows]


initialize_step4()


def get_dashboard_data(limit=10):
    """Read-only snapshot for the LAN dashboard."""
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        summary_row = conn.execute("""
            SELECT
                COUNT(*) AS total_triggers,
                COALESCE(SUM(CASE WHEN trigger_source='motion' THEN 1 ELSE 0 END),0) AS motion_triggers,
                COALESCE(SUM(CASE WHEN trigger_source='manual' THEN 1 ELSE 0 END),0) AS manual_triggers,
                COALESCE(SUM(CASE WHEN classification='bird' THEN 1 ELSE 0 END),0) AS bird_bursts,
                COALESCE(SUM(CASE WHEN classification='no_bird' THEN 1 ELSE 0 END),0) AS no_bird_bursts,
                COALESCE(SUM(CASE WHEN classification NOT IN ('bird','no_bird') OR classification IS NULL THEN 1 ELSE 0 END),0) AS pending_bursts,
                COALESCE(SUM(COALESCE(bird_photo_count,0)),0) AS bird_photos,
                COALESCE(SUM(COALESCE(discord_sent,0)),0) AS discord_notifications,
                COALESCE(SUM(COALESCE(deleted,0)),0) AS deleted_bursts
            FROM events
        """).fetchone()
        recent_rows = conn.execute("""
            SELECT timestamp, folder, trigger_source, classification,
                   COALESCE(photo_count,0) AS photo_count,
                   COALESCE(bird_photo_count,0) AS bird_photo_count,
                   COALESCE(discord_status,'unknown') AS discord_status
            FROM events ORDER BY id DESC LIMIT ?
        """, (max(1, min(int(limit), 50)),)).fetchall()
        usage = conn.execute("SELECT requests FROM api_usage WHERE month=?",
                             (current_month(),)).fetchone()
    summary = dict(summary_row)
    summary['api_requests'] = usage[0] if usage else 0
    summary['api_limit'] = MONTHLY_API_LIMIT
    return {'summary': summary, 'recent': [dict(row) for row in recent_rows]}
