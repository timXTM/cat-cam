"""Cached CatCam gallery previews, generated after capture or on demand.

Full-resolution originals are never modified. The cache mirrors the photo
archive's YYYY-MM-DD/HH-MM-SS/01.jpg ... 06.jpg directory layout.
"""
import logging
import os
import queue
import threading
from pathlib import Path

from PIL import Image

CACHE_DIR = Path('/home/pi/catcam_data/thumbnails')
MAX_SIZE = (420, 420)
JPEG_QUALITY = 72
_EXPECTED = tuple(f'{n:02d}.jpg' for n in range(1, 7))
_jobs = queue.Queue(maxsize=16)
_started = False
_start_lock = threading.Lock()


def thumbnail_path(photo):
    """Map a photo path to its thumbnail without trusting arbitrary paths."""
    photo = Path(photo)
    # The server already validates the photo path; this is defense in depth.
    if (photo.name not in _EXPECTED or
            not photo.parent.name.replace('-', '').isdigit() or
            not photo.parent.parent.name.replace('-', '').isdigit()):
        raise ValueError('Invalid CatCam photo path')
    return CACHE_DIR / photo.parent.parent.name / photo.parent.name / photo.name


def ensure_thumbnail(photo):
    """Return an up-to-date cached thumbnail; generate it if missing/stale."""
    photo = Path(photo)
    cache_file = thumbnail_path(photo)
    source_stat = photo.stat()
    if cache_file.is_file() and cache_file.stat().st_mtime_ns >= source_stat.st_mtime_ns:
        return cache_file

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_file.with_name(cache_file.name + f'.{threading.get_ident()}.tmp')
    try:
        with Image.open(photo) as source:
            source.thumbnail(MAX_SIZE, Image.Resampling.LANCZOS)
            if source.mode != 'RGB':
                source = source.convert('RGB')
            source.save(temporary, format='JPEG', quality=JPEG_QUALITY)
        # Set thumbnail mtime to source mtime so subsequent requests are cached.
        os.utime(temporary, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
        os.replace(temporary, cache_file)
    finally:
        temporary.unlink(missing_ok=True)
    return cache_file


def _worker():
    while True:
        event_dir = _jobs.get()
        try:
            count = 0
            for name in _EXPECTED:
                photo = event_dir / name
                if photo.is_file():
                    try:
                        ensure_thumbnail(photo)
                        count += 1
                    except (OSError, ValueError) as exc:
                        logging.warning('Thumbnail generation failed for %s: %s', photo, exc)
            print(f'Thumbnails ready: {count}/6 for {event_dir}', flush=True)
        except Exception:
            logging.exception('CatCam thumbnail worker error')
        finally:
            _jobs.task_done()


def start_worker():
    global _started
    with _start_lock:
        if not _started:
            threading.Thread(target=_worker, name='CatCamThumbnails', daemon=True).start()
            _started = True


def queue_event(event_dir):
    """Generate thumbnails asynchronously after capture; never block camera."""
    try:
        _jobs.put_nowait(Path(event_dir))
    except queue.Full:
        logging.warning('Thumbnail queue full for %s; will generate on gallery visit', event_dir)


def delete_event_thumbnails(event_dir):
    """Delete cached thumbnails for an already-deleted photo event.

    This is only called by the retention worker *after* the original six photos
    have been deleted. Unknown files and symlinks are never removed.
    """
    event_dir = Path(event_dir)
    cache_dir = CACHE_DIR / event_dir.parent.name / event_dir.name
    if cache_dir.is_symlink() or cache_dir.parent.is_symlink():
        raise ValueError('Refusing to delete through a symlinked thumbnail directory')
    if not cache_dir.is_dir():
        return 0
    deleted = 0
    for name in _EXPECTED:
        thumb = cache_dir / name
        if thumb.is_symlink():
            raise ValueError(f'Refusing symlinked thumbnail {thumb}')
        if thumb.is_file():
            thumb.unlink()
            deleted += 1
    try:
        cache_dir.rmdir()
    except OSError:
        # Leave unexpected files alone; do not recursively delete anything.
        logging.warning('Thumbnail cache folder not empty: %s', cache_dir)
    try:
        cache_dir.parent.rmdir()
    except OSError:
        pass
    return deleted
