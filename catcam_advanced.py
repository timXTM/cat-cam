"""Validated, persistent CatCam advanced settings. Never stores credentials."""
import json
import math
import threading
from pathlib import Path

FILE = Path('/home/pi/catcam_advanced_settings.json')
DEFAULTS = {
    'motion_enabled': True,
    'pixel_difference': 20,
    'sample_interval': 0.25,
    'capture_cooldown': 5.0,
    'burst_interval': 0.4,
    'discord_enabled': True,
    'cleanup_enabled': True,
    'retention_hours': 24,
    'cleanup_interval_minutes': 15,
    'thumbnail_max_size': 420,
    'thumbnail_quality': 72,
    'preview_interval': 0.5,
    'mounting_orientation': 'sideways_ccw',
    'rotation_override': 'auto',
    'gallery_default': 'bird',
    'vision_start_photo': 1,
    # Local AI is not activated until the Pi 4 service integration is installed.
    'detection_engine': 'google_vision',
    'local_ai_host': '192.168.1.75',
    'local_ai_port': 8765,
    'local_ai_photo_root': '/mnt/494USB/CatCam Wildlife',
    'local_ai_confidence': 0.25,
    'local_ai_species_enabled': True,
    'local_ai_timeout': 120,

    'timezone': 'America/New_York',
}
LIMITS = {
    'pixel_difference': (1, 255, int),
    'sample_interval': (0.1, 3, float),
    'capture_cooldown': (0, 3600, float),
    'burst_interval': (0, 10, float),
    'retention_hours': (1, 720, int),
    'cleanup_interval_minutes': (5, 1440, int),
    'thumbnail_max_size': (160, 1000, int),
    'thumbnail_quality': (40, 95, int),
    'preview_interval': (0.25, 5, float),
    'vision_start_photo': (1, 6, int),
    'local_ai_port': (1, 65535, int),
    'local_ai_confidence': (0.05, 0.95, float),
    'local_ai_timeout': (15, 300, int),

}
MOUNTINGS = {'normal': 0, 'sideways_cw': 270, 'upside_down': 180, 'sideways_ccw': 90}
OVERRIDES = {'auto', '0', '90', '180', '270'}
BOOLEAN_KEYS = {'motion_enabled', 'discord_enabled', 'cleanup_enabled', 'local_ai_species_enabled'}
_lock = threading.RLock()
_values = dict(DEFAULTS)


def validate(changes):
    if not isinstance(changes, dict):
        raise ValueError('Settings must be an object')
    validated = {}
    for key, value in changes.items():
        if key == 'detection_engine':
            if value not in ('google_vision', 'local_ai'):
                raise ValueError('Unknown detection engine')
        elif key == 'local_ai_host':
            import ipaddress
            try:
                ipaddress.ip_address(value)
            except (ValueError, TypeError):
                raise ValueError('Local AI host must be an IP address')
        elif key == 'local_ai_photo_root':
            from pathlib import PurePosixPath
            if (not isinstance(value, str) or len(value) > 255 or
                not value.startswith('/') or '..' in PurePosixPath(value).parts or
                any(ord(c) < 32 for c in value)):
                raise ValueError('Photo folder must be an absolute path on the Pi 4')
        elif key == 'gallery_default':
            if value not in ('all', 'bird', 'no_bird'): raise ValueError('Invalid gallery default')
        elif key == 'timezone':
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            if not isinstance(value, str) or len(value)>100: raise ValueError('Invalid timezone')
            try: ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError): raise ValueError('Unknown IANA timezone')
        elif key == 'mounting_orientation':
            if value not in MOUNTINGS: raise ValueError('Invalid mounting orientation')
        elif key == 'rotation_override':
            if value not in OVERRIDES: raise ValueError('Invalid rotation override')
        elif key in BOOLEAN_KEYS:
            if type(value) is not bool:
                raise ValueError(f'{key} must be true or false')
        elif key in LIMITS:
            low, high, kind = LIMITS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'{key} must be a number')
            if kind is int and int(value) != value:
                raise ValueError(f'{key} must be a whole number')
            value = kind(value)
            if not low <= value <= high:
                raise ValueError(f'{key} must be between {low} and {high}')
        else:
            raise ValueError(f'Unknown setting: {key}')
        validated[key] = value
    return validated


def get(key=None):
    with _lock:
        return _values[key] if key else dict(_values)


def update(changes, reset=False):
    validated = validate(changes)
    with _lock:
        new = dict(DEFAULTS if reset else _values)
        new.update(validated)
        FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = FILE.with_suffix('.tmp')
        temp.write_text(json.dumps(new, indent=2))
        temp.replace(FILE)
        _values.update(new)
        return dict(_values)


def load():
    try:
        raw = json.loads(FILE.read_text())
        if not isinstance(raw, dict):
            raise ValueError('Expected object')
        clean = validate({k: v for k, v in raw.items() if k in DEFAULTS})
        with _lock:
            _values.update(clean)
    except FileNotFoundError:
        pass
    except (ValueError, OSError) as exc:
        print(f'Advanced settings invalid; defaults in use: {exc}', flush=True)


load()


def output_rotation():
    """Clockwise rotation in degrees for the selected physical mounting."""
    with _lock:
        override = _values['rotation_override']
        return MOUNTINGS[_values['mounting_orientation']] if override == 'auto' else int(override)
