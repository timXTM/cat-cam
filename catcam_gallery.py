"""Read-only historical capture gallery; never invokes Google Vision."""
import sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import catcam_activity
import catcam_stats

BASE_DIR = Path('/home/pi/wildlife')
TZ = ZoneInfo('America/New_York')


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
    # A separate unfiltered query ensures broad type options are not narrowed by selection.
    types = activity['available_bird_types']
    if bird_type:
        types = catcam_activity.get_activity()['available_bird_types']
    details = {}
    db = Path(catcam_stats.DB_PATH)
    if db.is_file():
        with sqlite3.connect('file:' + str(db.resolve()) + '?mode=ro', uri=True, timeout=10) as conn:
            for folder, classification, deleted in conn.execute('SELECT folder, classification, deleted FROM events WHERE folder IS NOT NULL'):
                if folder:
                    details[str(Path(folder))] = (classification, bool(deleted))
    first_hour = int(start_hour) if start_hour not in ('', None) else None
    last_hour = int(end_hour) if end_hour not in ('', None) else None
    events = []
    if BASE_DIR.is_dir():
        for date_dir in BASE_DIR.iterdir():
            if not date_dir.is_dir() or not date_dir.name.startswith('20'):
                continue
            if start and date_dir.name < start or end and date_dir.name > end:
                continue
            for burst in date_dir.iterdir():
                if not burst.is_dir():
                    continue
                try:
                    local = datetime.strptime(date_dir.name + '/' + burst.name, '%Y-%m-%d/%H-%M-%S').replace(tzinfo=TZ)
                except ValueError:
                    continue
                if first_hour is not None:
                    h = local.hour
                    if not (first_hour <= h <= last_hour if first_hour <= last_hour else h >= first_hour or h <= last_hour):
                        continue
                folder = str(burst)
                bird = bird_map.get(folder)
                classification, deleted = details.get(folder, ('unknown', False))
                if deleted:
                    continue
                if mode == 'bird' and not bird:
                    continue
                if mode == 'no_bird' and classification != 'no_bird':
                    continue
                if bird_type and not bird:
                    continue
                photos = sorted(p.name for p in burst.glob('*.jpg') if p.is_file())[:6]
                if not photos:
                    continue
                events.append({'date': date_dir.name, 'event': burst.name,
                    'timestamp': local.isoformat(), 'classification': 'bird' if bird else classification,
                    'bird_type': bird['bird_type'] if bird else None,
                    'photos': photos})
    events.sort(key=lambda e: (e['date'], e['event']), reverse=order == 'newest')
    total = len(events)
    return {'events': events[(page-1)*page_size:page*page_size], 'total': total,
            'page': page, 'page_size': page_size, 'available_bird_types': types}
