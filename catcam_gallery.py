"""Read-only historical capture gallery; never invokes Google Vision."""
import sqlite3
import threading
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import catcam_activity
import catcam_stats
import catcam_advanced

BASE_DIR = Path('/home/pi/wildlife')
# Historical capture folders always use Eastern time.
# This is independent of the user-selected display timezone.
CAPTURE_TZ = ZoneInfo('America/New_York')
LEGACY_REFRESH_SECONDS = 300
_legacy_lock = threading.Lock()
_legacy_snapshot = None
_legacy_refreshed_at = 0.0
_legacy_base_dir = None
_legacy_refreshing = False


def _capture_time(folder, display_tz):
    """Reject paths outside the archive and malformed capture folder names."""
    if folder.parent.parent != BASE_DIR:
        return None
    try:
        original = datetime.strptime(
            folder.parent.name + '/' + folder.name, '%Y-%m-%d/%H-%M-%S'
        ).replace(tzinfo=CAPTURE_TZ)
    except ValueError:
        return None
    return original.astimezone(display_tz)


def _scan_archive(known_folders):
    """Index folders with photos once, for captures older than the event database."""
    folders = {}
    if BASE_DIR.is_dir():
        for date_dir in BASE_DIR.iterdir():
            if not date_dir.is_dir() or not date_dir.name.startswith('20'):
                continue
            for burst in date_dir.iterdir():
                if not burst.is_dir():
                    continue
                if str(burst) in known_folders:
                    continue
                # The database supplies modern event counts without disk scans.
                # Index photo presence only for historical folders.
                photos = sorted(p.name for p in burst.glob('*.jpg') if p.is_file())[:6]
                if photos:
                    folders[str(burst)] = photos
    return folders


def _refresh_legacy(known_folders):
    global _legacy_snapshot, _legacy_refreshed_at, _legacy_base_dir, _legacy_refreshing
    try:
        snapshot = _scan_archive(known_folders)
        with _legacy_lock:
            _legacy_snapshot = snapshot
            _legacy_refreshed_at = time.monotonic()
            _legacy_base_dir = BASE_DIR
    finally:
        with _legacy_lock:
            _legacy_refreshing = False


def _archive_snapshot(known_folders):
    """Refresh historical photo availability off the request thread when stale."""
    global _legacy_refreshing
    with _legacy_lock:
        if _legacy_snapshot is None or _legacy_base_dir != BASE_DIR:
            # Initial discovery must finish before an All bursts response so
            # historical photos are never silently omitted from the count.
            initial = True
        else:
            initial = False
            if (not _legacy_refreshing and
                    time.monotonic() - _legacy_refreshed_at >= LEGACY_REFRESH_SECONDS):
                _legacy_refreshing = True
                threading.Thread(target=_refresh_legacy, args=(known_folders,), daemon=True,
                                 name='CatCamGalleryIndex').start()
            return _legacy_snapshot
    if initial:
        # Only one initial scan runs, even when several viewers open together.
        with _legacy_initial_lock:
            with _legacy_lock:
                if _legacy_snapshot is not None and _legacy_base_dir == BASE_DIR:
                    return _legacy_snapshot
            _refresh_legacy(known_folders)
            with _legacy_lock:
                return _legacy_snapshot


_legacy_initial_lock = threading.Lock()


def gallery(mode='all', bird_type='', start='', end='', start_hour='', end_hour='', order='newest', page=1, page_size=20):
    if mode not in ('all', 'bird', 'no_bird'):
        raise ValueError('Invalid mode')
    if order not in ('newest', 'oldest'):
        raise ValueError('Invalid order')
    try:
        page = int(page)
    except (ValueError, TypeError):
        raise ValueError('Invalid page')
    if not 1 <= page <= 100000:
        raise ValueError('Invalid page')
    # Reuse the existing date/hour/type validation and hierarchy.
    activity = catcam_activity.get_activity(start=start or None, end=end or None,
        start_hour=start_hour or None, end_hour=end_hour or None,
        bird_type=bird_type or None)
    bird_map = {}
    for event in activity['events']:
        folder = event.get('folder')
        if folder:
            bird_map[str(Path(folder))] = event
    types = activity['available_bird_types']
    if bird_type:
        types = catcam_activity.get_activity()['available_bird_types']

    display_tz = ZoneInfo(catcam_advanced.get('timezone'))
    first_hour = int(start_hour) if start_hour not in ('', None) else None
    last_hour = int(end_hour) if end_hour not in ('', None) else None
    candidates = {}
    db = Path(catcam_stats.DB_PATH)
    if db.is_file():
        with sqlite3.connect('file:' + str(db.resolve()) + '?mode=ro', uri=True, timeout=10) as conn:
            for folder, classification, deleted, photo_count in conn.execute(
                    'SELECT folder, classification, deleted, photo_count FROM events WHERE folder IS NOT NULL ORDER BY id'):
                if folder:
                    candidates[str(Path(folder))] = (classification, bool(deleted), photo_count or 0)

    # Database events can be filtered and paginated without walking the archive.
    # Only All bursts can contain historical folders lacking a database row.
    legacy = _archive_snapshot(frozenset(candidates)) if mode == 'all' and not bird_type else {}
    folders = candidates.keys() | legacy.keys()
    matches = []
    for folder in folders:
        classification, deleted, photo_count = candidates.get(folder, ('unknown', False, 0))
        if deleted:
            continue
        is_legacy = folder not in candidates
        if is_legacy and not legacy[folder]:
            continue
        burst = Path(folder)
        # An older database row can have photos even if its recorded count is
        # zero. Check those few exceptions without scanning ordinary bursts.
        if not is_legacy and photo_count <= 0 and not any(p.is_file() for p in burst.glob('*.jpg')):
            continue
        local = _capture_time(burst, display_tz)
        if local is None:
            continue
        if start and local.date().isoformat() < start or end and local.date().isoformat() > end:
            continue
        if first_hour is not None:
            h = local.hour
            if not (first_hour <= h <= last_hour if first_hour <= last_hour else h >= first_hour or h <= last_hour):
                continue
        bird = bird_map.get(folder)
        if mode == 'bird' and not bird:
            continue
        if mode == 'no_bird' and classification != 'no_bird':
            continue
        if bird_type and not bird:
            continue
        matches.append((burst, local, classification, bird, legacy.get(folder) if is_legacy else None))
    matches.sort(key=lambda item: (item[0].parent.name, item[0].name), reverse=order == 'newest')
    total = len(matches)
    events = []
    for burst, local, classification, bird, legacy_photos in matches[(page-1)*page_size:page*page_size]:
        # Verify only the returned page's files. The capture worker and cleanup
        # worker update the DB for modern events, so no full archive walk is needed.
        photos = (legacy_photos if legacy_photos is not None else
                  sorted(p.name for p in burst.glob('*.jpg') if p.is_file())[:6])
        if not photos:
            continue
        events.append({'date': burst.parent.name, 'event': burst.name,
            'timestamp': local.isoformat(), 'classification': 'bird' if bird else classification,
            'bird_type': bird['bird_type'] if bird else None,
            'species_confidence': bird.get('species_confidence') if bird else None,
            'detection_engine': bird.get('detection_engine') if bird else None,
            'ai_species': bird.get('ai_species') if bird else None,
            'ai_common_name': bird.get('ai_common_name') if bird else None,
            'ai_species_score': bird.get('ai_species_score') if bird else None,
            'confirmed_species': bird.get('confirmed_species') if bird else None,
            'species_status': bird.get('species_status') if bird else None,
            'photos': photos})
    return {'events': events, 'total': total,
            'page': page, 'page_size': page_size, 'available_bird_types': types}
