from picamera2 import Picamera2
import numpy as np
import requests
import re
import subprocess
import time
import os
import io
import socket
import threading
import json
from urllib.parse import urlparse, unquote, parse_qs
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image


# ============================================================
# CatCam configuration
# ============================================================

WIDTH = 320
HEIGHT = 240

PIXEL_DIFF_THRESHOLD = 20

# Motion percentage required INSIDE the ROI is loaded below and is web-adjustable.

SAMPLE_INTERVAL = 0.25

BURST_COUNT = 6
BURST_INTERVAL = 0.4
COOLDOWN = 5

BASE_DIR = Path("/home/pi/wildlife")


# ============================================================
# Motion-detection ROI
# ============================================================

# Coordinates refer to the UNROTATED 320x240 lores stream.
#
# This ROI corresponds approximately to the red rectangle
# selected for the bird-feeder area.
#
# Full lores frame:
#   X = 0 through 319
#   Y = 0 through 239
#
# ROI:
#   X = 30 through 224
#   Y = 0 through 164
#
# The ROI affects ONLY motion detection.
# Saved photographs remain full-frame.

DEFAULT_ROI = {"x1": 30, "y1": 0, "x2": 225, "y2": 165}
DEFAULT_MOTION_THRESHOLD = 10.0
DEFAULT_FOCUS_POSITION = 1.0
SETTINGS_FILE = Path("/home/pi/catcam_settings.json")
settings_lock = threading.Lock()

ROI_X1 = DEFAULT_ROI["x1"]
ROI_Y1 = DEFAULT_ROI["y1"]
ROI_X2 = DEFAULT_ROI["x2"]
ROI_Y2 = DEFAULT_ROI["y2"]
MOTION_THRESHOLD = DEFAULT_MOTION_THRESHOLD
FOCUS_POSITION = DEFAULT_FOCUS_POSITION
AUTOFOCUS = False

current_motion_percent = 0.0
current_motion_lock = threading.Lock()


def validate_settings(x1, y1, x2, y2, threshold, focus_position=None):
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    threshold = float(threshold)
    if not (0 <= x1 < x2 <= WIDTH and 0 <= y1 < y2 <= HEIGHT):
        raise ValueError("ROI must stay inside the 320x240 motion frame.")
    if (x2 - x1) < 10 or (y2 - y1) < 10:
        raise ValueError("ROI must be at least 10x10 pixels.")
    if not (0.5 <= threshold <= 30.0):
        raise ValueError("Trigger threshold must be between 0.5% and 30.0%.")
    if focus_position is None:
        focus_position = FOCUS_POSITION
    focus_position = float(focus_position)
    if not (0.0 <= focus_position <= 32.0):
        raise ValueError("Focus position must be between 0.0 and 32.0 diopters.")
    return x1, y1, x2, y2, threshold, focus_position


def apply_settings(x1, y1, x2, y2, threshold, focus_position=None, autofocus=None, save=True):
    global ROI_X1, ROI_Y1, ROI_X2, ROI_Y2, MOTION_THRESHOLD, FOCUS_POSITION, AUTOFOCUS
    x1, y1, x2, y2, threshold, focus_position = validate_settings(x1, y1, x2, y2, threshold, focus_position)
    if autofocus is None:
        autofocus = AUTOFOCUS
    if not isinstance(autofocus, bool):
        raise ValueError("Autofocus must be true or false.")
    with settings_lock:
        AUTOFOCUS = autofocus
        ROI_X1, ROI_Y1, ROI_X2, ROI_Y2 = x1, y1, x2, y2
        MOTION_THRESHOLD = threshold
        FOCUS_POSITION = focus_position
        if save:
            temp = SETTINGS_FILE.with_suffix(".tmp")
            temp.write_text(json.dumps({
                "roi": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                "motion_threshold": threshold,
                "focus_position": focus_position,
                "autofocus": autofocus
            }, indent=2))
            temp.replace(SETTINGS_FILE)
    return {
        "roi": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "motion_threshold": threshold,
        "focus_position": focus_position,
        "autofocus": autofocus
    }


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        roi = data.get("roi", {})
        return apply_settings(
            roi.get("x1"), roi.get("y1"), roi.get("x2"), roi.get("y2"),
            data.get("motion_threshold"), data.get("focus_position", DEFAULT_FOCUS_POSITION), autofocus=data.get("autofocus", False), save=False
        )
    except FileNotFoundError:
        return apply_settings(**DEFAULT_ROI, threshold=DEFAULT_MOTION_THRESHOLD, focus_position=DEFAULT_FOCUS_POSITION, save=False)
    except Exception as exc:
        print(f"Settings file invalid; using defaults: {exc}", flush=True)
        return apply_settings(**DEFAULT_ROI, threshold=DEFAULT_MOTION_THRESHOLD, focus_position=DEFAULT_FOCUS_POSITION, save=False)


load_settings()


# ============================================================
# Image rotation
# ============================================================

# Camera is physically mounted sideways.
#
# jpegtran performs a lossless 90-degree clockwise JPEG
# rotation after each photograph is captured.

JPEGTRAN = "/usr/bin/jpegtran"
ROTATE_DEGREES = "90"


# ============================================================
# Discord configuration
# ============================================================

# Notifications ON:
#
#   touch ~/.catcam-discord
#
# Notifications OFF:
#
#   rm -f ~/.catcam-discord
#
# No service restart is required when changing the toggle.

DISCORD_TOGGLE = Path("/home/pi/.catcam-discord")

# Loaded by systemd from:
#
#   /etc/catcam.env

DISCORD_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL"
)

# Prevent network trouble from blocking CatCam indefinitely.

DISCORD_TIMEOUT = 20



# ============================================================
# LAN live-view configuration
# ============================================================

WEB_PORT = 8080
WEB_FRAME_INTERVAL = 0.5  # 2 fps maximum

latest_web_frame = None
latest_web_frame_lock = threading.Lock()

active_web_viewers = 0
active_web_viewers_lock = threading.Lock()

last_web_encode_time = 0.0

manual_trigger_requested = False
manual_trigger_lock = threading.Lock()
camera_busy = False
camera_busy_lock = threading.Lock()
GALLERY_EVENT_LIMIT = 20


def get_lan_ip():
    """Determine the Pi's LAN IP without contacting the Internet."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        address = sock.getsockname()[0]
    except Exception:
        address = "127.0.0.1"
    finally:
        sock.close()
    return address


class CatCamHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        return

    def send_body(self, status, body, content_type):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        global manual_trigger_requested
        path = urlparse(self.path).path

        if path == "/trigger":
            with camera_busy_lock:
                if camera_busy:
                    self.send_body(
                        409,
                        json.dumps({"ok": False, "message": "Camera is already capturing."}),
                        "application/json; charset=utf-8"
                    )
                    return
            with manual_trigger_lock:
                manual_trigger_requested = True
            self.send_body(
                202,
                json.dumps({"ok": True, "message": "Camera trigger accepted."}),
                "application/json; charset=utf-8"
            )
            return

        if path == "/settings":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 8192:
                    raise ValueError("Invalid request size.")
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if data.get("reset"):
                    settings = apply_settings(
                        **DEFAULT_ROI,
                        threshold=DEFAULT_MOTION_THRESHOLD,
                        focus_position=DEFAULT_FOCUS_POSITION,
                        autofocus=False, save=True
                    )
                else:
                    roi = data["roi"]
                    settings = apply_settings(
                        roi["x1"], roi["y1"], roi["x2"], roi["y2"],
                        data["motion_threshold"], data.get("focus_position", FOCUS_POSITION), autofocus=data.get("autofocus", AUTOFOCUS), save=True
                    )
                set_focus_controls(settings["autofocus"], settings["focus_position"])
                print(
                    "Web settings saved: "
                    f"ROI x={settings['roi']['x1']}:{settings['roi']['x2']}, "
                    f"y={settings['roi']['y1']}:{settings['roi']['y2']}; "
                    f"threshold={settings['motion_threshold']:.1f}%; "
                    f"focus={settings['focus_position']:.2f}",
                    flush=True
                )
                self.send_body(
                    200, json.dumps({"ok": True, **settings}),
                    "application/json; charset=utf-8"
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self.send_body(
                    400, json.dumps({"ok": False, "message": str(exc)}),
                    "application/json; charset=utf-8"
                )
            except Exception as exc:
                self.send_body(
                    500, json.dumps({"ok": False, "message": "Could not save settings."}),
                    "application/json; charset=utf-8"
                )
                print(f"Settings save failed: {exc}", flush=True)
            return

        self.send_error(404)

    def do_GET(self):
        global active_web_viewers
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path in ("/", "/index.html"):
            page = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CatCam</title>
<style>
body { margin:0; background:#111; color:#eee; font-family:system-ui,sans-serif; }
main { max-width:900px; margin:auto; padding:14px; }
.viewer { position:relative; width:min(640px,100%); margin:auto; line-height:0; user-select:none; touch-action:none; }
.live { display:block; width:100%; height:auto; max-height:82vh; object-fit:contain; }
#roi { position:absolute; box-sizing:border-box; border:3px solid #ff3b30; background:rgba(255,59,48,.08);
       cursor:move; line-height:normal; min-width:12px; min-height:12px; }
#handle { position:absolute; width:22px; height:22px; right:-11px; bottom:-11px; border-radius:50%;
          background:#ff3b30; border:2px solid white; box-sizing:border-box; cursor:nwse-resize; }
.panel { max-width:640px; margin:12px auto 24px; background:#1b1b1b; padding:12px; border-radius:9px; }
.readout { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:10px; }
.threshold-row,.focus-row { display:grid; grid-template-columns:1fr 90px; gap:10px; align-items:center; margin:10px 0; }
input[type=range] { width:100%; }
input[type=number] { width:100%; box-sizing:border-box; padding:7px; font-size:1rem; background:#292929; color:#eee; border:1px solid #555; border-radius:6px; }
.controls { display:flex; gap:10px; align-items:center; margin-top:12px; flex-wrap:wrap; }
button { border:0; border-radius:8px; padding:10px 16px; font-size:1rem; cursor:pointer; }
.status,.meta,.small { color:#bbb; font-size:.9rem; }
.events { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:14px; }
.event { background:#1d1d1d; border-radius:8px; padding:8px; }
.event img { width:100%; height:180px; object-fit:cover; border-radius:5px; }
.event a,a { color:#ddd; text-decoration:none; }
</style>
</head>
<body>
<main>
<h1>CatCam</h1>
<div class="viewer" id="viewer">
  <img class="live" id="live" src="/stream.mjpg" alt="CatCam live view">
  <div id="roi"><div id="handle"></div></div>
</div>

<div class="panel">
  <div class="readout">
    <strong id="motion">Current ROI motion: --</strong>
    <span id="roiText" class="small">ROI: --</span>
  </div>
  <label for="threshold">Trigger threshold</label>
  <div class="threshold-row">
    <input id="threshold" type="range" min="0.5" max="30" step="0.5">
    <input id="thresholdNumber" type="number" min="0.5" max="30" step="0.5">
  </div>
  <label><input id="autofocus" type="checkbox"> Continuous autofocus</label>
  <label for="focus">Manual focus (diopters; 0 = infinity)</label>
  <div class="focus-row">
    <input id="focus" type="range" min="0" max="5" step="0.05">
    <input id="focusNumber" type="number" min="0" max="32" step="0.05">
  </div>
  <div class="small">Low values focus farther away. Changes take effect when saved.</div>
  <div class="controls">
    <button id="save">Save settings</button>
    <button id="reset">Reset</button>
    <span id="settingsStatus" class="status"></span>
  </div>
  <div class="controls">
    <button id="trigger">Trigger camera</button>
    <span id="status" class="status">Monitoring</span>
  </div>
</div>

<h2>Recent captures</h2>
<div id="events" class="events">Loading...</div>
</main>
<script>
const W=320,H=240;
const viewer=document.getElementById("viewer");
const roiEl=document.getElementById("roi");
const handle=document.getElementById("handle");
const motionEl=document.getElementById("motion");
const roiText=document.getElementById("roiText");
const threshold=document.getElementById("threshold");
const thresholdNumber=document.getElementById("thresholdNumber");
const autofocus=document.getElementById("autofocus");
const focus=document.getElementById("focus");
function updateFocusEnabled(){focus.disabled=autofocus.checked;focusNumber.disabled=autofocus.checked;}
autofocus.addEventListener("change",updateFocusEnabled);
const focusNumber=document.getElementById("focusNumber");
const settingsStatus=document.getElementById("settingsStatus");
const statusEl=document.getElementById("status");
const button=document.getElementById("trigger");
const eventsEl=document.getElementById("events");
let roi={x1:30,y1:0,x2:225,y2:165};
let drag=null;

// Preview is rotated 90 degrees clockwise. Convert unrotated 320x240 ROI
// into percentages on the rotated 240x320 display.
function renderROI(){
  const left=(H-roi.y2)/H*100;
  const top=roi.x1/W*100;
  const width=(roi.y2-roi.y1)/H*100;
  const height=(roi.x2-roi.x1)/W*100;
  roiEl.style.left=left+"%"; roiEl.style.top=top+"%";
  roiEl.style.width=width+"%"; roiEl.style.height=height+"%";
  roiText.textContent=`ROI: x ${roi.x1}–${roi.x2-1}, y ${roi.y1}–${roi.y2-1}`;
}
function clamp(v,a,b){return Math.max(a,Math.min(b,v));}
function displayRect(){
  const r=viewer.getBoundingClientRect();
  return {w:r.width,h:r.height};
}
function eventPoint(e){
  const r=viewer.getBoundingClientRect();
  return {x:clamp(e.clientX-r.left,0,r.width),y:clamp(e.clientY-r.top,0,r.height)};
}
function roiFromDisplay(left,top,width,height){
  // Reverse the 90-degree-clockwise transform.
  let x1=Math.round((top/100)*W);
  let x2=Math.round(((top+height)/100)*W);
  let y2=Math.round(H-(left/100)*H);
  let y1=Math.round(H-((left+width)/100)*H);
  x1=clamp(x1,0,W-10); x2=clamp(x2,x1+10,W);
  y1=clamp(y1,0,H-10); y2=clamp(y2,y1+10,H);
  return {x1,y1,x2,y2};
}
function displayFromROI(r){
  return {left:(H-r.y2)/H*100,top:r.x1/W*100,
          width:(r.y2-r.y1)/H*100,height:(r.x2-r.x1)/W*100};
}

roiEl.addEventListener("pointerdown",e=>{
  e.preventDefault(); e.stopPropagation();
  const mode=(e.target===handle)?"resize":"move";
  roiEl.setPointerCapture(e.pointerId);
  drag={mode,start:eventPoint(e),box:displayFromROI(roi)};
});
roiEl.addEventListener("pointermove",e=>{
  if(!drag)return;
  const p=eventPoint(e), vr=displayRect();
  const dx=(p.x-drag.start.x)/vr.w*100, dy=(p.y-drag.start.y)/vr.h*100;
  let b={...drag.box};
  if(drag.mode==="move"){
    b.left=clamp(b.left+dx,0,100-b.width);
    b.top=clamp(b.top+dy,0,100-b.height);
  }else{
    b.width=clamp(b.width+dx,10/H*100,100-b.left);
    b.height=clamp(b.height+dy,10/W*100,100-b.top);
  }
  roi=roiFromDisplay(b.left,b.top,b.width,b.height);
  renderROI();
});
roiEl.addEventListener("pointerup",()=>drag=null);
roiEl.addEventListener("pointercancel",()=>drag=null);

threshold.addEventListener("input",()=>thresholdNumber.value=threshold.value);
thresholdNumber.addEventListener("input",()=>threshold.value=thresholdNumber.value);
focus.addEventListener("input",()=>focusNumber.value=focus.value);
focusNumber.addEventListener("input",()=>{ const v=Number(focusNumber.value); focus.value=Math.min(5,Math.max(0,v)); });

async function loadStatus(){
  try{
    const r=await fetch("/api/status",{cache:"no-store"});
    const s=await r.json();
    motionEl.textContent=`Current ROI motion: ${s.current_motion.toFixed(2)}% / ${s.motion_threshold.toFixed(1)}%`;
    motionEl.style.color=s.current_motion>=s.motion_threshold?"#ff6259":"";
  }catch(e){}
}
async function loadSettings(){
  const r=await fetch("/api/settings",{cache:"no-store"});
  const s=await r.json();
  roi=s.roi;
  threshold.value=s.motion_threshold;
  thresholdNumber.value=s.motion_threshold;
  autofocus.checked=!!s.autofocus; updateFocusEnabled();
  focus.value=Math.min(5,s.focus_position);
  focusNumber.value=s.focus_position;
  renderROI();
}
async function saveSettings(reset=false){
  settingsStatus.textContent=reset?"Resetting...":"Saving...";
  try{
    const body=reset?{reset:true}:{roi,motion_threshold:Number(thresholdNumber.value),focus_position:Number(focusNumber.value),autofocus:autofocus.checked};
    const r=await fetch("/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const s=await r.json();
    if(!r.ok)throw new Error(s.message||"Save failed");
    roi=s.roi; threshold.value=s.motion_threshold; thresholdNumber.value=s.motion_threshold;
    autofocus.checked=!!s.autofocus; updateFocusEnabled();
    focus.value=Math.min(5,s.focus_position); focusNumber.value=s.focus_position;
    renderROI(); settingsStatus.textContent="Saved and active";
    setTimeout(()=>settingsStatus.textContent="",2500);
  }catch(e){settingsStatus.textContent=e.message;}
}
document.getElementById("save").addEventListener("click",()=>saveSettings(false));
document.getElementById("reset").addEventListener("click",()=>saveSettings(true));

async function loadEvents(){
  try{
    const r=await fetch("/api/events",{cache:"no-store"});
    const events=await r.json();
    if(!events.length){eventsEl.textContent="No captures yet.";return;}
    eventsEl.innerHTML=events.map(e=>`
      <div class="event"><a href="/event?date=${encodeURIComponent(e.date)}&event=${encodeURIComponent(e.event)}">
      <img loading="lazy" src="${e.preview}" alt="">
      <div class="meta">${e.date} ${e.event.replaceAll("-",":")}</div>
      <div class="meta">${e.count} photos</div></a></div>`).join("");
  }catch(e){eventsEl.textContent="Could not load captures.";}
}
button.addEventListener("click",async()=>{
  button.disabled=true; statusEl.textContent="Requesting capture...";
  try{
    const r=await fetch("/trigger",{method:"POST"});
    const result=await r.json();
    if(!r.ok)throw new Error(result.message||"Trigger failed");
    statusEl.textContent="Capture requested";
    setTimeout(loadEvents,5000); setTimeout(loadEvents,15000); setTimeout(loadEvents,30000);
  }catch(e){statusEl.textContent=e.message;}
  setTimeout(()=>{button.disabled=false;statusEl.textContent="Monitoring";},3000);
});
loadSettings(); loadStatus(); loadEvents();
setInterval(loadStatus,1000);
</script>
</body>
</html>"""
            self.send_body(200, page, "text/html; charset=utf-8")
            return

        if path == "/stream.mjpg":
            self.send_response(200)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()

            with active_web_viewers_lock:
                active_web_viewers += 1
                count = active_web_viewers
            print(f"Live-view viewer connected ({count} active)", flush=True)

            try:
                while True:
                    with latest_web_frame_lock:
                        jpeg = latest_web_frame
                    if jpeg is None:
                        time.sleep(0.1)
                        continue
                    self.wfile.write(b"--FRAME\\r\\n")
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(jpeg)))
                    self.end_headers()
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\\r\\n")
                    self.wfile.flush()
                    time.sleep(WEB_FRAME_INTERVAL)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with active_web_viewers_lock:
                    active_web_viewers=max(0,active_web_viewers-1)
                    count=active_web_viewers
                print(f"Live-view viewer disconnected ({count} active)", flush=True)
            return

        if path == "/api/settings":
            with settings_lock:
                settings = {
                    "roi": {"x1": ROI_X1, "y1": ROI_Y1, "x2": ROI_X2, "y2": ROI_Y2},
                    "motion_threshold": MOTION_THRESHOLD,
                    "focus_position": FOCUS_POSITION,
                    "autofocus": AUTOFOCUS
                }
            self.send_body(200, json.dumps(settings), "application/json; charset=utf-8")
            return

        if path == "/api/status":
            with current_motion_lock:
                motion = current_motion_percent
            with settings_lock:
                threshold = MOTION_THRESHOLD
            self.send_body(
                200,
                json.dumps({"current_motion": motion, "motion_threshold": threshold}),
                "application/json; charset=utf-8"
            )
            return

        if path == "/api/events":
            events=[]
            if BASE_DIR.exists():
                for date_dir in sorted((p for p in BASE_DIR.iterdir() if p.is_dir()), reverse=True):
                    for event_dir in sorted((p for p in date_dir.iterdir() if p.is_dir()), reverse=True):
                        photos=sorted(event_dir.glob("*.jpg"))
                        if photos:
                            events.append({
                                "date":date_dir.name,
                                "event":event_dir.name,
                                "count":len(photos),
                                "preview":f"/photo/{date_dir.name}/{event_dir.name}/{photos[0].name}"
                            })
                        if len(events)>=GALLERY_EVENT_LIMIT: break
                    if len(events)>=GALLERY_EVENT_LIMIT: break
            self.send_body(200,json.dumps(events),"application/json; charset=utf-8")
            return

        if path == "/event":
            params=parse_qs(parsed.query)
            date_name=params.get("date",[""])[0]
            event_name=params.get("event",[""])[0]
            safe="0123456789-"
            if (not date_name or not event_name or
                any(c not in safe for c in date_name) or
                any(c not in safe for c in event_name)):
                self.send_error(400); return
            event_dir=BASE_DIR/date_name/event_name
            if not event_dir.is_dir():
                self.send_error(404); return
            photos=sorted(event_dir.glob("*.jpg"))
            images="".join(
                f'<a href="/photo/{date_name}/{event_name}/{p.name}">'
                f'<img loading="lazy" src="/photo/{date_name}/{event_name}/{p.name}" alt="{p.name}"></a>'
                for p in photos
            )
            page=f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CatCam event</title><style>
body{{background:#111;color:#eee;font-family:system-ui,sans-serif;margin:0}}
main{{max-width:1100px;margin:auto;padding:14px}} a{{color:#ddd}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
.gallery img{{width:100%;height:auto;border-radius:6px}}
</style></head><body><main><p><a href="/">← CatCam</a></p>
<h1>{date_name} {event_name.replace("-",":")}</h1>
<div class="gallery">{images}</div></main></body></html>"""
            self.send_body(200,page,"text/html; charset=utf-8")
            return

        if path.startswith("/photo/"):
            parts=path.split("/")
            if len(parts)!=5:
                self.send_error(404); return
            _,_,date_name,event_name,filename=parts
            safe="0123456789-"
            if (
                not date_name
                or not event_name
                or any(c not in safe for c in date_name)
                or any(c not in safe for c in event_name)
                or filename != Path(filename).name
                or not filename.lower().endswith(".jpg")
            ):
                self.send_error(400)
                return

            photo = BASE_DIR / date_name / event_name / filename

            try:
                photo.resolve().relative_to(BASE_DIR.resolve())
            except ValueError:
                self.send_error(403)
                return

            if not photo.is_file():
                self.send_error(404)
                return

            try:
                self.send_response(200)
                self.send_header("Content-Type","image/jpeg")
                self.send_header("Content-Length",str(photo.stat().st_size))
                self.send_header("Cache-Control","private, max-age=3600")
                self.end_headers()
                with open(photo,"rb") as f:
                    while True:
                        chunk=f.read(65536)
                        if not chunk: break
                        self.wfile.write(chunk)
            except (BrokenPipeError,ConnectionResetError):
                pass
            return

        self.send_error(404)

def start_web_server():
    """Start the LAN-only CatCam web server."""
    web_host = get_lan_ip()
    try:
        server = ThreadingHTTPServer(
            (web_host, WEB_PORT),
            CatCamHandler
        )
        print(
            f"CatCam live view: http://{web_host}:{WEB_PORT}/",
            flush=True
        )
        server.serve_forever()
    except Exception as error:
        # Live view must never stop wildlife photography.
        print(f"CatCam live view failed: {error}", flush=True)


def update_web_frame(rgb_frame):
    """Encode the 640x480 RGB888 main stream only while a viewer is connected."""
    global latest_web_frame, last_web_encode_time

    with active_web_viewers_lock:
        if active_web_viewers <= 0:
            return

    now = time.monotonic()
    if now - last_web_encode_time < WEB_FRAME_INTERVAL:
        return

    last_web_encode_time = now

    try:
        image = Image.fromarray(rgb_frame.astype(np.uint8), "RGB")
        image = image.transpose(Image.Transpose.ROTATE_270)

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=72)

        with latest_web_frame_lock:
            latest_web_frame = buffer.getvalue()

    except Exception as exc:
        print(f"Web preview error: {exc}", flush=True)


def rotate_photo(photo):
    """
    Losslessly rotate one JPEG 90 degrees clockwise.

    jpegtran writes to a temporary file first. Only after
    successful rotation is the original photograph replaced.

    If rotation fails, the original photograph is preserved.
    """

    temp_photo = photo.with_name(
        photo.stem + ".rotating.jpg"
    )

    try:

        with open(temp_photo, "wb") as output_file:

            result = subprocess.run(
                [
                    JPEGTRAN,
                    "-rotate",
                    ROTATE_DEGREES,
                    "-copy",
                    "all",
                    str(photo)
                ],
                stdout=output_file,
                stderr=subprocess.PIPE,
                timeout=30
            )

        if result.returncode != 0:

            error_text = result.stderr.decode(
                errors="replace"
            ).strip()

            print(
                f"Rotation failed for {photo}: "
                f"{error_text}",
                flush=True
            )

            temp_photo.unlink(
                missing_ok=True
            )

            return False

        # Make sure jpegtran actually produced a file
        # before replacing the original.

        if (
            not temp_photo.exists()
            or temp_photo.stat().st_size == 0
        ):

            print(
                f"Rotation failed for {photo}: "
                f"temporary output is empty",
                flush=True
            )

            temp_photo.unlink(
                missing_ok=True
            )

            return False

        # Atomic replacement on the same filesystem.

        temp_photo.replace(photo)

        print(
            f"Rotated {photo}",
            flush=True
        )

        return True

    except Exception as error:

        print(
            f"Rotation failed for {photo}: {error}",
            flush=True
        )

        temp_photo.unlink(
            missing_ok=True
        )

        # Original photograph remains intact.

        return False


# ============================================================
# Discord notification
# ============================================================

def send_discord_notification(
    photos,
    event_dir,
    motion_percent,
    event_timestamp
):
    """
    Send ONE Discord webhook message containing all six
    photographs from the motion event.
    """

    # Check the toggle at every event.

    if not DISCORD_TOGGLE.exists():

        print(
            "Discord notification skipped: "
            "notifications OFF",
            flush=True
        )

        return

    if not DISCORD_WEBHOOK_URL:

        print(
            "Discord notification skipped: "
            "webhook URL not configured",
            flush=True
        )

        return

    timestamp_text = event_timestamp.strftime(
        "%Y-%m-%d %I:%M:%S %p"
    )

    message = (
        f"CatCam motion detected\n"
        f"{timestamp_text}\n"
        f"ROI motion: {motion_percent:.1f}%\n"
        f"{len(photos)} photos captured\n"
        f"Folder: {event_dir}"
    )

    open_files = []

    try:

        # A list of tuples allows requests to upload all
        # photographs in a single Discord webhook POST.

        files = []

        for index, photo in enumerate(photos):

            image_file = open(
                photo,
                "rb"
            )

            open_files.append(
                image_file
            )

            files.append(
                (
                    f"files[{index}]",
                    (
                        photo.name,
                        image_file,
                        "image/jpeg"
                    )
                )
            )

        response = requests.post(
            DISCORD_WEBHOOK_URL,
            data={
                "content": message
            },
            files=files,
            timeout=DISCORD_TIMEOUT
        )

        response.raise_for_status()

        print(
            f"Discord notification sent "
            f"with {len(photos)} photos",
            flush=True
        )

    except Exception as error:

        # Discord failure must never stop photography.

        print(
            f"Discord notification failed: {error}",
            flush=True
        )

    finally:

        for image_file in open_files:

            try:
                image_file.close()

            except Exception:
                pass


# ============================================================
# Camera setup
# ============================================================

picam2 = Picamera2()

# v7 normal state: process only a 320x240 YUV stream.
motion_config = picam2.create_video_configuration(
    main={"size": (640, 480), "format": "RGB888"},
    lores={"size": (WIDTH, HEIGHT), "format": "YUV420"},
    buffer_count=2
)

# Full resolution exists only while a motion-triggered burst is captured.
still_config = picam2.create_still_configuration(
    main={"size": (4608, 2592), "format": "RGB888"},
    buffer_count=1
)


def set_focus_controls(autofocus, position):
    if autofocus:
        picam2.set_controls({"AfMode": 2})
    else:
        picam2.set_controls({"AfMode": 0, "LensPosition": position})


picam2.configure(motion_config)
picam2.start()
set_focus_controls(AUTOFOCUS, FOCUS_POSITION)

print("Allowing exposure to settle...", flush=True)
time.sleep(3)

previous = None
last_trigger = 0
last_motion_log_time = 0.0

print("Wildlife camera running.", flush=True)
print("Camera idle mode: 640x480 RGB888 preview + 320x240 YUV420 motion", flush=True)
print("Capture mode: 4608x2592 RGB888 still capture on motion/manual trigger", flush=True)
print(
    f"Motion ROI: x={ROI_X1}:{ROI_X2}, y={ROI_Y1}:{ROI_Y2} "
    f"({ROI_X2-ROI_X1}x{ROI_Y2-ROI_Y1}, "
    f"{(ROI_X2-ROI_X1)*(ROI_Y2-ROI_Y1)} pixels)",
    flush=True
)
print(f"Motion settings file: {SETTINGS_FILE}", flush=True)
print(f"ROI motion threshold: {MOTION_THRESHOLD:.1f}%", flush=True)
print(f"Manual focus position: {FOCUS_POSITION:.2f} diopters", flush=True)
print(
    "Discord notifications: "
    + ("ON" if DISCORD_TOGGLE.exists() else "OFF"),
    flush=True
)


def capture_full_resolution_burst(event_dir):
    """Switch to full resolution for the burst, then return to motion mode."""
    captured_photos = []

    switch_start = time.monotonic()
    picam2.switch_mode(still_config)
    set_focus_controls(AUTOFOCUS, FOCUS_POSITION)
    switch_to_still_seconds = time.monotonic() - switch_start

    burst_start = time.monotonic()
    first_photo_seconds = None

    try:
        for i in range(1, BURST_COUNT + 1):
            filename = event_dir / f"{i:02d}.jpg"
            capture_start = time.monotonic()
            picam2.capture_file(str(filename))

            if first_photo_seconds is None:
                first_photo_seconds = time.monotonic() - burst_start

            captured_photos.append(filename)
            print(
                f"Saved {filename} "
                f"(capture {time.monotonic() - capture_start:.2f}s)",
                flush=True
            )

            if i < BURST_COUNT:
                time.sleep(BURST_INTERVAL)

    finally:
        back_start = time.monotonic()
        picam2.switch_mode(motion_config)
        set_focus_controls(AUTOFOCUS, FOCUS_POSITION)
        switch_back_seconds = time.monotonic() - back_start

    return (
        captured_photos,
        switch_to_still_seconds,
        first_photo_seconds,
        switch_back_seconds
    )


def run_capture_event(changed_percent, trigger_source):
    global camera_busy

    with camera_busy_lock:
        if camera_busy:
            return
        camera_busy = True

    try:
        event_timestamp=datetime.now()
        event_dir=BASE_DIR/event_timestamp.strftime("%Y-%m-%d")/event_timestamp.strftime("%H-%M-%S")
        event_dir.mkdir(parents=True,exist_ok=True)

        print(f"{trigger_source.upper()} TRIGGER: {changed_percent:.2f}% ROI motion",flush=True)
        print(f"Event folder: {event_dir}",flush=True)
        print(f"Capturing {BURST_COUNT} photos...",flush=True)

        captured_photos,switch_to_still_seconds,first_photo_seconds,switch_back_seconds = (
            capture_full_resolution_burst(event_dir)
        )

        print(
            "Burst complete. "
            f"Switch to still: {switch_to_still_seconds:.2f}s; "
            f"first photo: {first_photo_seconds:.2f}s; "
            f"switch back: {switch_back_seconds:.2f}s",
            flush=True
        )

        print("Rotating photographs...",flush=True)
        successes=0
        for photo in captured_photos:
            if rotate_photo(photo): successes+=1
        print(f"Rotation complete: {successes}/{len(captured_photos)} successful",flush=True)

        send_discord_notification(
            captured_photos,event_dir,changed_percent,event_timestamp
        )
    finally:
        with camera_busy_lock:
            camera_busy=False


# ============================================================
# Start LAN web server
# ============================================================

web_thread = threading.Thread(
    target=start_web_server,
    daemon=True
)
web_thread.start()

# ============================================================
# Motion detection loop
# ============================================================

try:
    while True:
        request = picam2.capture_request()
        try:
            frame = request.make_array("lores")
            gray = frame[:HEIGHT, :WIDTH].astype(np.int16)

            with active_web_viewers_lock:
                viewers = active_web_viewers
            if viewers > 0:
                preview_rgb = request.make_array("main")
                update_web_frame(preview_rgb)
        finally:
            request.release()

        changed_percent=0.0

        if previous is not None:
            with settings_lock:
                roi_x1, roi_y1, roi_x2, roi_y2 = ROI_X1, ROI_Y1, ROI_X2, ROI_Y2
                motion_threshold = MOTION_THRESHOLD
            roi_pixels = (roi_x2-roi_x1) * (roi_y2-roi_y1)
            current_roi=gray[roi_y1:roi_y2,roi_x1:roi_x2]
            previous_roi=previous[roi_y1:roi_y2,roi_x1:roi_x2]
            diff=np.abs(current_roi-previous_roi)
            changed_pixels=np.count_nonzero(diff>PIXEL_DIFF_THRESHOLD)
            changed_percent=changed_pixels/roi_pixels*100

            with current_motion_lock:
                current_motion_percent = changed_percent

            motion_log_now=time.monotonic()
            if changed_percent>0.0 and motion_log_now-last_motion_log_time>=1.0:
                print(f"ROI Motion: {changed_percent:6.2f}%",flush=True)
                last_motion_log_time=motion_log_now

        manual_trigger=False
        with manual_trigger_lock:
            if manual_trigger_requested:
                manual_trigger_requested=False
                manual_trigger=True

        now=time.time()
        motion_trigger=(
            previous is not None
            and changed_percent>=motion_threshold
            and now-last_trigger>=COOLDOWN
        )

        if manual_trigger or motion_trigger:
            last_trigger=now
            run_capture_event(
                changed_percent,
                "manual" if manual_trigger else "motion"
            )

            time.sleep(0.5)
            request = picam2.capture_request()
            try:
                frame = request.make_array("lores")
                gray = frame[:HEIGHT, :WIDTH].astype(np.int16)

                with active_web_viewers_lock:
                    viewers = active_web_viewers
                if viewers > 0:
                    preview_rgb = request.make_array("main")
                    update_web_frame(preview_rgb)
            finally:
                request.release()

        previous=gray.copy()
        time.sleep(SAMPLE_INTERVAL)

except KeyboardInterrupt:
    print("\nStopping wildlife camera.",flush=True)

finally:
    picam2.stop()
