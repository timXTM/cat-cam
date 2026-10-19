#!/usr/bin/env python3
"""Add an all-history Bird Photo Gallery and clickable bird-type links.
Safe, repeatable installation. No database changes or Google Vision requests.
"""
from pathlib import Path
import py_compile
import shutil
import sys

root=Path(__file__).resolve().parent
camera=root/'wildlife_camera.py'
activity=root/'catcam_bird_activity.html'
gallery=root/'catcam_bird_gallery.html'
for p in (camera,activity,gallery):
    if not p.is_file():sys.exit(f'ERROR: Missing {p.name}. No changes made.')
c=camera.read_text(encoding='utf-8')
a=activity.read_text(encoding='utf-8')
route='''        if path in ("/bird-gallery", "/bird-gallery/"):
            try:
                from pathlib import Path as _BirdGalleryPath
                page = (_BirdGalleryPath(__file__).resolve().parent / "catcam_bird_gallery.html").read_text(encoding="utf-8")
                self.send_body(200, page, "text/html; charset=utf-8")
            except Exception as exc:
                print(f"Bird Gallery page failed: {exc}", flush=True)
                self.send_body(500, "Bird Gallery unavailable", "text/plain; charset=utf-8")
            return

'''
marker='        if path == "/api/events":'
if 'if path in ("/bird-gallery", "/bird-gallery/"):' not in c:
    if c.count(marker)!=1:sys.exit('ERROR: Cannot find unique page-route insertion point. No changes made.')
    c=c.replace(marker,route+marker,1)

# Link chart labels to a full historical photo gallery, using URL encoding.
old='''<span class="name" title="${escapeHtml(x.bird_type)}">${escapeHtml(x.bird_type)}</span>'''
new='''<a class="name" title="View all photos of ${escapeHtml(x.bird_type)}" href="/bird-gallery?bird_type=${encodeURIComponent(x.bird_type)}">${escapeHtml(x.bird_type)} ↗</a>'''
if old in a:
    if a.count(old)!=1:sys.exit('ERROR: Unexpected multiple bird type chart labels. No changes made.')
    a=a.replace(old,new,1)
elif new not in a:sys.exit('ERROR: Bird Activity chart code has changed. No changes made.')
oldcell='''<td>${escapeHtml(e.bird_type)}</td>'''
newcell='''<td><a href="/bird-gallery?bird_type=${encodeURIComponent(e.bird_type)}" title="View all photos of this bird type">${escapeHtml(e.bird_type)} ↗</a></td>'''
if oldcell in a:
    if a.count(oldcell)!=1:sys.exit('ERROR: Unexpected multiple bird type table cells. No changes made.')
    a=a.replace(oldcell,newcell,1)
elif newcell not in a:sys.exit('ERROR: Bird Activity table code has changed. No changes made.')
# Add navigation to bird gallery from Bird Activity page.
navneedle='<a class="active" href="/bird-activity">Bird Activity</a>'
navadd=navneedle+'<a href="/bird-gallery">Bird Photos</a>'
if 'href="/bird-gallery">Bird Photos</a>' not in a:
    if a.count(navneedle)!=1:sys.exit('ERROR: Bird Activity navigation changed. No changes made.')
    a=a.replace(navneedle,navadd,1)

updates=[]
for p,newtext in ((camera,c),(activity,a)):
    oldtext=p.read_text(encoding='utf-8')
    if oldtext!=newtext:updates.append((p,oldtext,newtext))
if not updates:
    print('SUCCESS: Bird type gallery already installed. No changes made.')
    sys.exit(0)
backups=[]
try:
    for p,old,newtext in updates:
        backup=p.with_name(p.name+'.before_bird_type_gallery')
        shutil.copy2(p,backup)
        backups.append((p,backup))
        p.write_text(newtext,encoding='utf-8')
    py_compile.compile(str(camera),doraise=True)
    assert 'if path in ("/bird-gallery", "/bird-gallery/"):' in camera.read_text(encoding='utf-8')
    assert 'href="/bird-gallery?bird_type=${encodeURIComponent(x.bird_type)}"' in activity.read_text(encoding='utf-8')
except Exception as exc:
    for p,backup in reversed(backups):shutil.copy2(backup,p)
    sys.exit(f'ERROR: {exc}. Original files restored.')
print('SUCCESS: Historical bird photo gallery and clickable bird-type links installed.')
print('Python syntax check passed. Restart CatCam to enable /bird-gallery.')
for p,backup in backups:print('Backup:',backup.name)
