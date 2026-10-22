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
        "error", "first_bird_photo", "bird_labels_json",
        "detection_engine",
        "ai_species",
        "ai_species_score",
        "confirmed_species",
        "species_status"
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
        if 'first_bird_photo' not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN first_bird_photo INTEGER")
        if 'bird_labels_json' not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN bird_labels_json TEXT")

        new_columns = {
            "detection_engine": "TEXT",
            "ai_species": "TEXT",
            "ai_species_score": "REAL",
            "confirmed_species": "TEXT",
            "species_status": "TEXT DEFAULT 'unreviewed'",
        }
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
        for name, definition in new_columns.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE events ADD COLUMN {name} {definition}")



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
                   first_bird_photo, bird_labels_json,
                   COALESCE(discord_status,'unknown') AS discord_status
            FROM events ORDER BY id DESC LIMIT ?
        """, (max(1, min(int(limit), 50)),)).fetchall()
        usage = conn.execute("SELECT requests FROM api_usage WHERE month=?",
                             (current_month(),)).fetchone()
    summary = dict(summary_row)
    summary['api_requests'] = usage[0] if usage else 0
    summary['api_limit'] = MONTHLY_API_LIMIT
    return {'summary': summary, 'recent': [dict(row) for row in recent_rows]}


def set_confirmed_species(folder, species):
    """Set or clear a human-verified species for a bird-positive burst only."""
    if species is not None:
        if not isinstance(species, str):
            raise ValueError('Species must be text')
        species = ' '.join(species.strip().split())
        if not 1 <= len(species) <= 100 or any(ord(c) < 32 for c in species):
            raise ValueError('Species name must be 1–100 printable characters')
    with connect() as conn:
        row = conn.execute('SELECT id, classification FROM events WHERE folder=? ORDER BY id DESC LIMIT 1',
                           (str(folder),)).fetchone()
        if not row or row[1] != 'bird':
            raise ValueError('Bird-positive event not found')
        conn.execute('UPDATE events SET confirmed_species=?, species_status=? WHERE id=?',
                     (species, 'confirmed' if species else 'unreviewed', row[0]))
    return {'confirmed_species': species, 'species_status': 'confirmed' if species else 'unreviewed'}


def get_event_details(folder):
    """Safe, read-only classification metadata for a burst and its six photos."""
    import json
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        event = conn.execute("""
            SELECT id, classification, first_bird_photo, bird_labels_json,
                   detection_engine, ai_species, ai_species_score,
                   confirmed_species, species_status
            FROM events WHERE folder=? ORDER BY id DESC LIMIT 1
        """, (str(folder),)).fetchone()
        if event is None:
            return {"classification": "unknown", "first_bird_photo": None,
                    "bird_labels": [], "photos": {}}
        rows = conn.execute("""
            SELECT photo_path, bird_detected, confidence, labels_json
            FROM photo_detections WHERE event_id=?
        """, (event['id'],)).fetchall()
    photo_data = {}
    for row in rows:
        photo_data[Path(row['photo_path']).name] = {
            'checked': True, 'bird_detected': bool(row['bird_detected']),
            'confidence': row['confidence'],
            'labels': json.loads(row['labels_json'] or '[]')
        }
    first = event['first_bird_photo']
    labels = json.loads(event['bird_labels_json'] or '[]')
    # Normalize both legacy Google Vision dictionaries and new plain-string labels.
    def label_name(value):
        if isinstance(value, dict):
            return str(value.get('name') or value.get('description') or '').strip()
        if isinstance(value, (list, tuple)):
            return label_name(value[0]) if value else ''
        return str(value).strip() if value is not None else ''

    def normalize_labels(values):
        if not isinstance(values, list):
            return []
        return [name for value in values if (name := label_name(value))]

    # Existing bird events predate the new metadata columns.
    if first is None:
        positive = sorted(name for name, result in photo_data.items() if result['bird_detected'])
        if positive:
            first = int(Path(positive[0]).stem)
            if not labels:
                labels = photo_data[positive[0]]['labels']
    # The API always exposes readable names, not raw dict objects.
    # Per-photo labels are independent: old bursts may have several checked photos.
    for result in photo_data.values():
        result['labels'] = normalize_labels(result['labels'])
    return {
        'classification': event['classification'],
        'detection_engine': event['detection_engine'] or 'google_vision',
        'ai_species': event['ai_species'],
        'ai_species_score': event['ai_species_score'],
        'confirmed_species': event['confirmed_species'],
        'species_status': event['species_status'],
        'first_bird_photo': first,
        'bird_labels': normalize_labels(labels),
        'photos': photo_data
    }
