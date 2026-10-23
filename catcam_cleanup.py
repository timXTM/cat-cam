"""Conservative retention cleanup for fully classified, non-bird CatCam bursts.

Run `python3 catcam_cleanup.py --dry-run` to preview eligible events.
Deletion only targets exact, database-verified six-photo burst directories.
"""
import argparse
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import catcam_stats
import catcam_thumbnails
import catcam_advanced

BASE_DIR = Path('/home/pi/wildlife').resolve()
RETENTION = timedelta(hours=24)
CHECK_INTERVAL = 15 * 60
EXPECTED_PHOTOS = tuple(f'{i:02d}.jpg' for i in range(1, 7))


def eligible_events(now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=catcam_advanced.get("retention_hours"))).isoformat()
    with catcam_stats.connect() as conn:
        return conn.execute('''
            SELECT e.id, e.timestamp, e.folder
            FROM events e
            WHERE e.classification = 'no_bird'
              AND e.confirmed_species IS NULL
              AND COALESCE(e.deleted, 0) = 0
              AND e.photo_count = 6
              AND COALESCE(e.bird_photo_count, 0) = 0
              AND e.timestamp <= ?
              AND (SELECT COUNT(*) FROM photo_detections p
                   WHERE p.event_id = e.id) = 6
              AND (SELECT COUNT(*) FROM photo_detections p
                   WHERE p.event_id = e.id AND p.bird_detected = 0) = 6
            ORDER BY e.id
        ''', (cutoff,)).fetchall()


def validated_photos(event_id, folder):
    """Return exact expected paths, or refuse to delete anything."""
    event_dir = Path(folder)
    # Reject symlinks in any part of the event's path, including date folder.
    if event_dir.is_symlink() or event_dir.parent.is_symlink():
        return None
    if event_dir.parent.parent != BASE_DIR:
        return None
    try:
        datetime.strptime(event_dir.parent.name, '%Y-%m-%d')
        datetime.strptime(event_dir.name, '%H-%M-%S')
    except ValueError:
        return None
    if not event_dir.is_dir():
        return None
    contents = list(event_dir.iterdir())
    if len(contents) != 6 or any(p.is_symlink() or not p.is_file() for p in contents):
        return None
    paths = [event_dir / name for name in EXPECTED_PHOTOS]
    if set(contents) != set(paths):
        return None
    with catcam_stats.connect() as conn:
        rows = conn.execute('''
            SELECT photo_path FROM photo_detections
            WHERE event_id=? AND bird_detected=0
        ''', (event_id,)).fetchall()
    if len(rows) != 6 or {r[0] for r in rows} != {str(p) for p in paths}:
        return None
    return paths


def cleanup_once(dry_run=False):
    removed = 0
    for event_id, timestamp, folder in eligible_events():
        paths = validated_photos(event_id, folder)
        if paths is None:
            logging.warning('Cleanup skipped event %s: folder/files failed safety checks', event_id)
            continue
        if dry_run:
            print(f'ELIGIBLE event {event_id} ({timestamp}): {folder} [6 photos]')
            continue
        try:
            # Serialize deletion with manual species confirmation.
            with catcam_stats.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")

                # Recheck eligibility under the write lock.
                eligible = conn.execute("""
                    SELECT 1 FROM events
                    WHERE id=?
                      AND classification='no_bird'
                      AND confirmed_species IS NULL
                      AND COALESCE(deleted, 0)=0
                      AND photo_count=6
                      AND COALESCE(bird_photo_count, 0)=0
                """, (event_id,)).fetchone()

                if not eligible:
                    continue

                # Revalidate files while holding the lock.
                paths = validated_photos(event_id, folder)
                if paths is None:
                    continue

                for photo in paths:
                    photo.unlink()

                Path(folder).rmdir()

                conn.execute("""
                    UPDATE events
                    SET deleted=1, deleted_at=?
                    WHERE id=?
                """, (
                    datetime.now(timezone.utc).isoformat(),
                    event_id
                ))

            # Remove cached thumbnails after the database transaction.
            try:
                thumb_count = catcam_thumbnails.delete_event_thumbnails(folder)
            except (OSError, ValueError):
                logging.exception('Thumbnail cleanup failed for event %s', event_id)
                thumb_count = 0

            removed += 1
            print(
                f'Deleted six non-bird photos and {thumb_count} thumbnails '
                f'for event {event_id}',
                flush=True
            )

        except OSError:
            logging.exception(
                'Cleanup failed for event %s; will not delete other files',
                event_id
            )

    return removed


def cleanup_worker():
    print('Non-bird photo cleanup started (24h retention, 15m checks)', flush=True)
    while True:
        try:
            if catcam_advanced.get("cleanup_enabled"):
                cleanup_once()
        except Exception:
            logging.exception('CatCam cleanup error')
        time.sleep(catcam_advanced.get("cleanup_interval_minutes") * 60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='List eligible bursts without deleting')
    args = parser.parse_args()
    if not args.dry_run:
        parser.error('Automatic deletion is managed by CatCam; standalone mode requires --dry-run')
    cleanup_once(dry_run=True)
