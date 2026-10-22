#!/usr/bin/env python3
"""CatCam LAN detector bridge. Run with ~/bird-detector/venv/bin/python.

Authenticated endpoints:
 GET /health
 GET /check-folder?path=<URL-encoded directory>
 POST /detect {folder, photo_base, confidence, roi, timeout}

No Pi Zero W changes are required to test this server.
"""
import hmac
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path.home() / 'bird-detector'
sys.path.insert(0, str(ROOT))
from detect_and_identify import analyze_burst

TOKEN_FILE = ROOT / 'server' / 'api_token'
DEFAULT_PHOTO_BASE = Path('/mnt/494USB/CatCam Wildlife')
BIND = os.environ.get('CATCAM_AI_BIND', '192.168.1.75')
PORT = int(os.environ.get('CATCAM_AI_PORT', '8765'))
BURST_RE = re.compile(r'^\d{4}-\d{2}-\d{2}/\d{2}-\d{2}-\d{2}$')
LOCK = threading.Lock()


def valid_base(value):
    if not isinstance(value, str) or not value.startswith('/') or len(value) > 500 or '\x00' in value:
        raise ValueError('photo_base must be an absolute directory path')
    base = Path(value).resolve(strict=True)
    if not base.is_dir():
        raise ValueError('Photo base is not a directory')
    return base


def valid_burst(base, folder):
    if not isinstance(folder, str) or not BURST_RE.fullmatch(folder):
        raise ValueError('folder must be YYYY-MM-DD/HH-MM-SS')
    target = (base / folder).resolve()
    if not target.is_relative_to(base):
        raise ValueError('Folder escapes photo base')
    return target


def wait_for_photos(directory, seconds):
    deadline = time.monotonic() + seconds
    names = [f'{n:02}.jpg' for n in range(1, 7)]
    previous = None
    stable_since = None
    while time.monotonic() < deadline:
        try:
            sizes = tuple((directory / name).stat().st_size for name in names)
        except (FileNotFoundError, OSError):
            sizes = None
        if sizes and all(size > 0 for size in sizes):
            if sizes == previous:
                if stable_since is not None and time.monotonic() - stable_since >= 2:
                    return
            else:
                previous = sizes
                stable_since = time.monotonic()
        else:
            previous = None
            stable_since = None
        time.sleep(0.5)
    raise TimeoutError('Timed out waiting for all six synchronized photos')


class Handler(BaseHTTPRequestHandler):
    server_version = 'CatCamLocalAI/0.1'

    def reply(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        provided = self.headers.get('X-CatCam-Token', '')
        if not hmac.compare_digest(provided, self.server.api_token):
            self.reply(401, {'error': 'Unauthorized'})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        parsed = urlsplit(self.path)
        if parsed.path == '/health':
            self.reply(200, {'status': 'ok', 'service': 'catcam-local-ai', 'version': 1,
                             'busy': LOCK.locked()})
        elif parsed.path == '/check-folder':
            try:
                path = parse_qs(parsed.query).get('path', [str(DEFAULT_PHOTO_BASE)])[0]
                base = valid_base(path)
                dates = sum(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.name))
                            for p in base.iterdir() if p.is_dir())
                self.reply(200, {'ok': True, 'path': str(base), 'date_folders': dates,
                                 'readable': os.access(base, os.R_OK | os.X_OK)})
            except (ValueError, OSError) as exc:
                self.reply(400, {'ok': False, 'error': str(exc)})
        else:
            self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if not self.authorized():
            return
        if urlsplit(self.path).path != '/detect':
            self.reply(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected JSON object')
            base = valid_base(data.get('photo_base', str(DEFAULT_PHOTO_BASE)))
            folder = data.get('folder')
            target = valid_burst(base, folder)
            confidence = data.get('confidence', 0.25)
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.01 <= confidence <= 1:
                raise ValueError('confidence must be between 0.01 and 1')
            roi = data.get('roi', [57, 57, 254, 160])
            if not isinstance(roi, list) or len(roi) != 4 or any(type(n) is not int for n in roi):
                raise ValueError('roi must be four integer coordinates')
            x1, y1, x2, y2 = roi
            if not (0 <= x1 < x2 <= 320 and 0 <= y1 < y2 <= 240):
                raise ValueError('roi is outside the 320x240 preview')
            identify_species = data.get('identify_species', True)
            if type(identify_species) is not bool:
                raise ValueError('identify_species must be true or false')
            timeout = data.get('timeout', 120)
            if type(timeout) is not int or not 10 <= timeout <= 300:
                raise ValueError('timeout must be 10–300 seconds')
        except (ValueError, TypeError, json.JSONDecodeError, OSError) as exc:
            self.reply(400, {'error': str(exc)})
            return
        if not LOCK.acquire(blocking=False):
            self.reply(503, {'error': 'Detector is processing another burst'})
            return
        try:
            wait_for_photos(target, timeout)
            result = analyze_burst(
                folder,
                photo_base=str(base),
                confidence=confidence,
                roi=tuple(roi),
                identify_species=identify_species
            )
            self.reply(200, result)
        except TimeoutError as exc:
            self.reply(504, {'error': str(exc)})
        except Exception as exc:
            self.log_error('Detection failed: %s', exc)
            self.reply(500, {'error': 'Detection failed; see Pi 4 server log'})
        finally:
            LOCK.release()


if __name__ == '__main__':
    token = TOKEN_FILE.read_text().strip()
    if len(token) < 32:
        raise SystemExit('API token missing or too short')
    server = ThreadingHTTPServer((BIND, PORT), Handler)
    server.api_token = token
    print(f'CatCam Local AI listening on {BIND}:{PORT}', flush=True)
    server.serve_forever()
