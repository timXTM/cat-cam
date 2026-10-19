#!/usr/bin/env python3
"""Safely install the CatCam Stage 2 Bird Activity page and navigation link.

Run from /home/pi/catcam after adding catcam_bird_activity.html.
Idempotent; backs up modified files; restores both on errors.
"""
from pathlib import Path
import py_compile
import shutil
import sys

root = Path(__file__).resolve().parent
camera = root / 'wildlife_camera.py'
dashboard = root / 'catcam_dashboard.html'
activity = root / 'catcam_bird_activity.html'

if not all(p.is_file() for p in (camera, dashboard, activity)):
    print('ERROR: wildlife_camera.py, catcam_dashboard.html, and catcam_bird_activity.html must be in the same directory.')
    sys.exit(1)

original_camera = camera.read_text(encoding='utf-8')
original_dashboard = dashboard.read_text(encoding='utf-8')

# Insert before existing, known API handler; no changes to capture logic.
marker = '        if path == "/api/events":'
route = '''        if path in ("/bird-activity", "/bird-activity/"):
            try:
                from pathlib import Path as _BirdActivityPath
                page = (_BirdActivityPath(__file__).resolve().parent / "catcam_bird_activity.html").read_text(encoding="utf-8")
                self.send_body(200, page, "text/html; charset=utf-8")
            except Exception as exc:
                print(f"Bird Activity page failed: {exc}", flush=True)
                self.send_body(500, "Bird Activity page unavailable", "text/plain; charset=utf-8")
            return

'''
if 'if path in ("/bird-activity", "/bird-activity/"):' in original_camera:
    changed_camera = original_camera
    print('Page route already installed; leaving it unchanged.')
elif original_camera.count(marker) == 1 and 'if path == "/api/bird-activity":' in original_camera:
    changed_camera = original_camera.replace(marker, route + marker, 1)
else:
    print('ERROR: Expected API endpoint or insertion point not found; no changes made.')
    sys.exit(1)

# Add an anchor to the existing nav without changing the dashboard JavaScript.
link = '<a href="/bird-activity" class="bird-activity-nav">🐦 Bird Activity</a>'
if 'class="bird-activity-nav"' in original_dashboard:
    changed_dashboard = original_dashboard
    print('Navigation link already installed; leaving it unchanged.')
else:
    nav_open = '<nav class="nav" aria-label="Main navigation">'
    nav_start = original_dashboard.find(nav_open)
    nav_end = original_dashboard.find('</nav>', nav_start) if nav_start != -1 else -1
    if nav_end == -1:
        print('ERROR: Expected dashboard navigation not found; no changes made.')
        sys.exit(1)
    changed_dashboard = original_dashboard[:nav_end] + link + original_dashboard[nav_end:]
    css = '.nav a.bird-activity-nav{display:inline-flex;align-items:center;border-radius:8px;padding:9px 15px;font-weight:650;color:var(--muted);white-space:nowrap}.nav a.bird-activity-nav:hover{background:var(--green-soft);color:var(--green)}'
    changed_dashboard = changed_dashboard.replace('</style>', css + '</style>', 1)

updates = [(camera, original_camera, changed_camera), (dashboard, original_dashboard, changed_dashboard)]
modified = [(p,old,new) for p,old,new in updates if old != new]
if not modified:
    print('SUCCESS: Stage 2 already installed. No changes made.')
    sys.exit(0)

backups = []
try:
    for p,old,new in modified:
        backup = p.with_name(p.name + '.before_bird_activity_stage2')
        shutil.copy2(p,backup)
        backups.append((p,backup))
        p.write_text(new,encoding='utf-8')
    py_compile.compile(str(camera),doraise=True)
    assert 'class="bird-activity-nav"' in dashboard.read_text(encoding='utf-8')
    assert 'if path in ("/bird-activity", "/bird-activity/"):' in camera.read_text(encoding='utf-8')
except Exception as exc:
    for p,backup in reversed(backups):
        shutil.copy2(backup,p)
    print('ERROR:',exc,'Original files restored.')
    sys.exit(1)
print('SUCCESS: Stage 2 page route and navigation link installed.')
print('Python syntax check passed.')
for _,backup in backups:print('Backup:',backup.name)
print('Next: sudo systemctl restart catcam.service')
