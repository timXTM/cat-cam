"""CatCam Stage 1: read-only, event-based bird activity analytics.

A detection-positive capture event counts once, regardless of six photos, repeat
triggers, or the number of Google Vision labels. No additional Vision calls.
"""
import json
import sqlite3
from collections import Counter
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
import catcam_advanced

DB_PATH = Path('/home/pi/catcam_data/catcam_stats.db')
LOCAL_TZ = ZoneInfo('America/New_York')

# Recognized species labels, with broader bird types as fallback.
# Extend the mapping when real Vision labels demonstrate new types.
SPECIES_ALIASES = {
    'northern cardinal': 'Northern cardinal',
    'cardinalis cardinalis': 'Northern cardinal',
    'house finch': 'House finch',
    'haemorhous mexicanus': 'House finch',
    'american goldfinch': 'American goldfinch',
    'spinus tristis': 'American goldfinch',
    'house sparrow': 'House sparrow',
    'passer domesticus': 'House sparrow',
    'blue jay': 'Blue jay',
    'cyanocitta cristata': 'Blue jay',
    'mourning dove': 'Mourning dove',
    'zenaida macroura': 'Mourning dove',
    'red-bellied woodpecker': 'Red-bellied woodpecker',
    'downy woodpecker': 'Downy woodpecker',
    'hairy woodpecker': 'Hairy woodpecker',
    'white-breasted nuthatch': 'White-breasted nuthatch',
    'tufted titmouse': 'Tufted titmouse',
    'black-capped chickadee': 'Black-capped chickadee',
    'carolina chickadee': 'Carolina chickadee',
    'american robin': 'American robin',
    'european starling': 'European starling',
    'common grackle': 'Common grackle',
    'dark-eyed junco': 'Dark-eyed junco',
    'song sparrow': 'Song sparrow',
    'chipping sparrow': 'Chipping sparrow',
    'red-winged blackbird': 'Red-winged blackbird',
    'rose-breasted grosbeak': 'Rose-breasted grosbeak',
    'indigo bunting': 'Indigo bunting',
    'gray catbird': 'Gray catbird',
}
# Explicit hierarchy: the category filter includes its identified descendants.
# Categories are practical feeder-identification groups, not necessarily strict
# biological taxa (e.g. 'Cardinal' is a broad common-name identification).
TYPE_PARENTS = {
    'Northern cardinal': 'Cardinal',
    'House finch': 'Finch',
    'American goldfinch': 'Finch',
    'House sparrow': 'Sparrow',
    'Song sparrow': 'Sparrow',
    'Chipping sparrow': 'Sparrow',
    'Red-bellied woodpecker': 'Woodpecker',
    'Downy woodpecker': 'Woodpecker',
    'Hairy woodpecker': 'Woodpecker',
    'Black-capped chickadee': 'Chickadee',
    'Carolina chickadee': 'Chickadee',
}
# Google Vision's generic labels can still be useful identifications.
BROAD_ALIASES = {
    'cardinal': 'Cardinal', 'cardinals': 'Cardinal',
    'finch': 'Finch', 'finches': 'Finch',
    'sparrow': 'Sparrow', 'sparrows': 'Sparrow',
    'woodpecker': 'Woodpecker', 'woodpeckers': 'Woodpecker',
    'chickadee': 'Chickadee', 'chickadees': 'Chickadee',
    'nuthatch': 'Nuthatch', 'nuthatches': 'Nuthatch',
    'dove': 'Dove', 'doves': 'Dove',
    'jay': 'Jay', 'jays': 'Jay',
    'blackbird': 'Blackbird', 'blackbirds': 'Blackbird',
    'warbler': 'Warbler', 'warblers': 'Warbler',
    'wren': 'Wren', 'wrens': 'Wren',
    'hummingbird': 'Hummingbird', 'hummingbirds': 'Hummingbird',
}
UNKNOWN = 'Unknown bird type' 
MIN_SPECIES_CONFIDENCE = 0.65
MIN_LEAD = 0.10


def _labels(value):
    if not value:
        return []
    try:
        entries = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return []
    if not isinstance(entries, list):
        return []
    normalized = []
    for item in entries:
        if isinstance(item, dict):
            name = item.get('name') or item.get('description')
            confidence = item.get('confidence', item.get('score'))
        elif isinstance(item, str):
            name, confidence = item, None
        else:
            continue
        if not isinstance(name, str) or not name.strip():
            continue
        try:
            score = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            score = None
        normalized.append({'name': name.strip(), 'confidence': score})
    return normalized


def identify_bird_type(labels):
    """Return (most specific defensible bird type, confidence).

    Prefer a specific species when confidence >= 65% and the top species
    exceeds a competing species by >= 10 percentage points. Otherwise,
    fall back to a confident broader label (including the common parent
    of ambiguous species, if appropriate). Never count generic 'Bird'
    as a meaningful bird type.
    """
    species_scores, broad_scores = {}, {}
    for label in labels:
        name = str(label.get('name', '')).strip().casefold()
        score = label.get('confidence')
        if score is None or not isinstance(score, (float, int)) or not 0 <= score <= 1:
            continue
        species = SPECIES_ALIASES.get(name)
        broad = BROAD_ALIASES.get(name)
        if species:
            species_scores[species] = max(species_scores.get(species, 0), score)
        if broad:
            broad_scores[broad] = max(broad_scores.get(broad, 0), score)
    ranked = sorted(species_scores.items(), key=lambda x: (-x[1], x[0]))
    if ranked and ranked[0][1] >= MIN_SPECIES_CONFIDENCE:
        if len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= MIN_LEAD:
            return ranked[0]
        # Competing species with a shared parent still support that broader type.
        plausible = [name for name, score in ranked
                     if score >= MIN_SPECIES_CONFIDENCE and ranked[0][1] - score < MIN_LEAD]
        parents = {TYPE_PARENTS.get(name) for name in plausible}
        if len(parents) == 1 and None not in parents:
            parent = parents.pop()
            broad_scores[parent] = max(broad_scores.get(parent, 0), ranked[0][1])
    candidates = [(name, score) for name, score in broad_scores.items()
                  if score >= MIN_SPECIES_CONFIDENCE]
    if candidates:
        return sorted(candidates, key=lambda x: (-x[1], x[0]))[0]
    return UNKNOWN, None


def identify_species(labels):
    """Backward-compatible alias; returns a bird type, not always a species."""
    return identify_bird_type(labels)


def matches_bird_type(assigned, requested):
    """A broad filter includes specific types beneath it."""
    if assigned.casefold() == requested.casefold():
        return True
    parent = TYPE_PARENTS.get(assigned)
    return parent is not None and parent.casefold() == requested.casefold()


def _local_datetime(timestamp):
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            # Existing CatCam record_trigger writes UTC; preserve that convention.
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(catcam_advanced.get('timezone')))
    except (TypeError, ValueError, AttributeError):
        return None


def _parse_date(value, field):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f'{field} must be YYYY-MM-DD')


def _parse_hour(value, field):
    if value is None or value == '':
        return None
    try:
        hour = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field} must be an integer from 0 to 23')
    if str(hour) != str(value) or not 0 <= hour <= 23:
        raise ValueError(f'{field} must be an integer from 0 to 23')
    return hour


def get_activity(start=None, end=None, start_hour=None, end_hour=None,
                 bird_type=None, db_path=DB_PATH):
    """Return aggregate counts and matching event identifiers for shared filters.

    Date range inclusive; local clock hours inclusive, supports overnight ranges.
    A bird-positive event is one observation, never six photographs.
    """
    start_date = _parse_date(start, 'start')
    end_date = _parse_date(end, 'end')
    if start_date and end_date and end_date < start_date:
        raise ValueError('end must be on or after start')
    from_hour = _parse_hour(start_hour, 'start_hour')
    to_hour = _parse_hour(end_hour, 'end_hour')
    if (from_hour is None) != (to_hour is None):
        raise ValueError('start_hour and end_hour must be provided together')
    if bird_type is not None and (not isinstance(bird_type, str) or len(bird_type) > 100):
        raise ValueError('Invalid bird_type')
    bird_type = bird_type or None

    # Fetch only bird-positive capture events and their first checked positive photo.
    # LEFT JOIN supports older events without photo-level records.
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro', uri=True, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('''
            SELECT e.id, e.timestamp, e.folder, e.trigger_source,
                   e.first_bird_photo, e.bird_labels_json,
                    e.detection_engine, e.ai_species, e.ai_species_score,
                    e.confirmed_species, e.species_status,
                   (SELECT p.labels_json FROM photo_detections p
                    WHERE p.event_id=e.id AND p.bird_detected=1
                    ORDER BY p.photo_path LIMIT 1) AS photo_labels
            FROM events e
            WHERE e.classification='bird'
            ORDER BY e.timestamp, e.id
        ''').fetchall()

    matches = []
    by_hour, by_day, by_type = Counter(), Counter(), Counter()
    all_types = set()
    for row in rows:
        labels = _labels(row['photo_labels'])
        # Legacy event-level names lack confidence; use scored photo labels when available.
        species, confidence = identify_bird_type(labels)
        engine = row['detection_engine'] or 'google_vision'
        ai_species = row['ai_species'] if engine == 'local_ai' else None
        ai_score = row['ai_species_score'] if engine == 'local_ai' else None
        confirmed = row['confirmed_species']
        if confirmed:
            species, confidence = confirmed, None
        elif ai_species:
            species, confidence = ai_species, ai_score
        all_types.add(species)
        dt = _local_datetime(row['timestamp'])
        if dt is None:
            continue
        day = dt.date()
        if start_date and day < start_date or end_date and day > end_date:
            continue
        hour = dt.hour
        if from_hour is not None:
            inside = (from_hour <= hour <= to_hour if from_hour <= to_hour
                      else hour >= from_hour or hour <= to_hour)
            if not inside:
                continue
        if bird_type and not matches_bird_type(species, bird_type):
            continue
        by_hour[hour] += 1
        by_day[day.isoformat()] += 1
        by_type[species] += 1
        matches.append({
            'id': row['id'], 'timestamp_local': dt.isoformat(),
            'folder': row['folder'], 'trigger_source': row['trigger_source'],
            'bird_type': species, 'species_confidence': confidence,
             'detection_engine': engine, 'ai_species': ai_species,
             'ai_species_score': ai_score, 'confirmed_species': confirmed,
             'species_status': row['species_status'] or 'unreviewed',
             'first_bird_photo': row['first_bird_photo'],
            'labels': labels,
        })

    return {
        'metric': 'bird_positive_capture_events',
        'description': 'One event per capture burst with a confirmed bird detection; not individual bird visits.',
        'timezone': catcam_advanced.get('timezone'),
        'filters': {'start': start, 'end': end, 'start_hour': from_hour,
                    'end_hour': to_hour, 'bird_type': bird_type},
        'total_events': len(matches),
        'by_hour': [{'hour': h, 'events': by_hour[h]} for h in range(24)],
        'by_day': [{'date': d, 'events': n} for d, n in sorted(by_day.items())],
        'by_bird_type': [{'bird_type': s, 'events': n}
                         for s, n in sorted(by_type.items(), key=lambda item: (-item[1], item[0]))],
        'available_bird_types': sorted(all_types | {TYPE_PARENTS[t] for t in all_types if t in TYPE_PARENTS}),
        'events': matches,
    }
