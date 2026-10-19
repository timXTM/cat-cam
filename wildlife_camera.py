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
import catcam_stats
import bird_detection
import catcam_cleanup
import catcam_thumbnails
import catcam_advanced
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
# Rotation is read from catcam_advanced.output_rotation() at runtime.


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

        if path == "/api/advanced-settings":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Expected settings object")
                values = catcam_advanced.update(data.get('settings', {}), reset=data.get('reset') is True)
                self.send_body(200, json.dumps({'ok': True, 'settings': values}), 'application/json; charset=utf-8')
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_body(400, json.dumps({'ok': False, 'message': str(exc)}), 'application/json; charset=utf-8')
            except OSError as exc:
                print(f'Advanced settings save failed: {exc}', flush=True)
                self.send_body(500, json.dumps({'ok': False, 'message': 'Unable to save settings'}), 'application/json; charset=utf-8')
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
            # Serve the standalone, lightweight dashboard template.
            # Keeping the HTML separate makes future UI changes safer.
            try:
                page = (Path(__file__).resolve().parent / "catcam_dashboard.html").read_text(encoding="utf-8")
            except OSError as exc:
                print(f"Dashboard template unavailable: {exc}", flush=True)
                self.send_error(503, "Dashboard template unavailable")
                return
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
                    time.sleep(catcam_advanced.get("preview_interval"))
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with active_web_viewers_lock:
                    active_web_viewers=max(0,active_web_viewers-1)
                    count=active_web_viewers
                print(f"Live-view viewer disconnected ({count} active)", flush=True)
            return

        if path == "/api/advanced-settings":
            self.send_body(200, json.dumps({'settings': catcam_advanced.get()}), 'application/json; charset=utf-8')
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

        if path == "/api/statistics":
            try:
                data = catcam_stats.get_dashboard_data()
                self.send_body(200, json.dumps(data), "application/json; charset=utf-8")
            except Exception as exc:
                print(f"Statistics API failed: {exc}", flush=True)
                self.send_body(500, json.dumps({"error": "Statistics unavailable"}),
                               "application/json; charset=utf-8")
            return


        if path == "/api/bird-activity":
            try:
                from urllib.parse import parse_qs
                import catcam_activity

                params = parse_qs(parsed.query)

                def param(name):
                    return params.get(name, [None])[0]

                data = catcam_activity.get_activity(
                    start=param("start"),
                    end=param("end"),
                    start_hour=param("start_hour"),
                    end_hour=param("end_hour"),
                    bird_type=param("bird_type"),
                )

                self.send_body(
                    200,
                    json.dumps(data),
                    "application/json; charset=utf-8"
                )

            except ValueError as exc:
                self.send_body(
                    400,
                    json.dumps({"error": str(exc)}),
                    "application/json; charset=utf-8"
                )

            except Exception as exc:
                print(f"Bird Activity API failed: {exc}", flush=True)
                self.send_body(
                    500,
                    json.dumps({"error": "Bird Activity unavailable"}),
                    "application/json; charset=utf-8"
                )

            return

        if path in ("/bird-activity", "/bird-activity/"):
            try:
                from pathlib import Path as _BirdActivityPath
                page = (_BirdActivityPath(__file__).resolve().parent / "catcam_bird_activity.html").read_text(encoding="utf-8")
                self.send_body(200, page, "text/html; charset=utf-8")
            except Exception as exc:
                print(f"Bird Activity page failed: {exc}", flush=True)
                self.send_body(500, "Bird Activity page unavailable", "text/plain; charset=utf-8")
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
                                "preview":f"/thumb/{date_dir.name}/{event_dir.name}/{photos[0].name}",
                                "detection":catcam_stats.get_event_details(event_dir)
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
            # Use the same navigation, appearance, and browser-local dark-mode
            # preference as the main dashboard. The template builds photo cards
            # client-side; JSON is escaped so filenames cannot inject markup.
            try:
                template = (Path(__file__).resolve().parent / "catcam_event.html").read_text(encoding="utf-8")
            except OSError as exc:
                print(f"Event template unavailable: {exc}", flush=True)
                self.send_error(503, "Event template unavailable")
                return
            event_data = {
                "date": date_name,
                "event": event_name,
                "detection": catcam_stats.get_event_details(event_dir),
                "photos": [
                    {"url": f"/photo/{date_name}/{event_name}/{p.name}",
                     "thumb": f"/thumb/{date_name}/{event_name}/{p.name}"}
                    for p in photos
                ],
            }
            payload = json.dumps(event_data, ensure_ascii=True).replace("<", "\\u003c")
            page = template.replace("__CATCAM_EVENT_DATA__", payload)
            self.send_body(200,page,"text/html; charset=utf-8")
            return

        if path.startswith("/photo/") or path.startswith("/thumb/"):
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

            # Serve small cached previews. Generate lazily as a fallback for
            # historical bursts or any queued thumbnail job still in progress.
            image_to_send = photo
            if path.startswith("/thumb/"):
                try:
                    image_to_send = catcam_thumbnails.ensure_thumbnail(photo)
                except (OSError, ValueError) as exc:
                    print(f"Thumbnail generation failed: {exc}", flush=True)
                    self.send_error(500, "Thumbnail unavailable")
                    return

            try:
                self.send_response(200)
                self.send_header("Content-Type","image/jpeg")
                self.send_header("Content-Length",str(image_to_send.stat().st_size))
                self.send_header("Cache-Control","private, max-age=3600")
                self.end_headers()
                with open(image_to_send,"rb") as f:
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
        rotation = catcam_advanced.output_rotation()
        if rotation:
            image = image.transpose({
                90: Image.Transpose.ROTATE_270,
                180: Image.Transpose.ROTATE_180,
                270: Image.Transpose.ROTATE_90,
            }[rotation])

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=72)

        with latest_web_frame_lock:
            latest_web_frame = buffer.getvalue()

    except Exception as exc:
        print(f"Web preview error: {exc}", flush=True)


def rotate_photo(photo, degrees):
    """
    Apply the selected clockwise rotation to a saved JPEG.

    jpegtran writes to a temporary file first. Only after
    successful rotation is the original photograph replaced.

    If rotation fails, the original photograph is preserved.
    """

    if degrees == 0:
        return photo.is_file() and photo.stat().st_size > 0

    temp_photo = photo.with_name(
        photo.stem + ".rotating.jpg"
    )

    try:

        with open(temp_photo, "wb") as output_file:

            result = subprocess.run(
                [
                    JPEGTRAN,
                    "-rotate",
                    str(degrees),
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
    event_timestamp,
    first_bird_photo=None,
    bird_labels=None
):
    """
    Send ONE Discord webhook message containing all six
    photographs from the motion event.
    """

    # Check the toggle at every event.

    if not catcam_advanced.get("discord_enabled") or not DISCORD_TOGGLE.exists():

        print(
            "Discord notification skipped: "
            "notifications OFF",
            flush=True
        )

        return False

    if not DISCORD_WEBHOOK_URL:

        print(
            "Discord notification skipped: "
            "webhook URL not configured",
            flush=True
        )

        return False

    timestamp_text = event_timestamp.strftime(
        "%Y-%m-%d %I:%M:%S %p"
    )

    labels_text = ", ".join(str(label) for label in (bird_labels or [])[:8]) or "No descriptive labels"
    message = (
        f"CatCam bird detected\n"
        f"{timestamp_text}\n"
        f"ROI motion: {motion_percent:.1f}%\n"
        f"Bird detected in photo {first_bird_photo or '?'}\n"
        f"Google Vision labels: {labels_text}\n"
        f"All {len(photos)} burst photos attached (only checked photos are classified).\n"
        f"Folder: {event_dir}"
    )

    open_files = []

    try:

        # A list of tuples allows requests to upload all
        # photographs in a single Discord webhook POST.

        files = []

        for index, photo in enumerate(photos):

            # Send lightweight copies to Discord; never modify archived originals.
            with Image.open(photo) as original:
                copy = original.copy()
                copy.thumbnail((1600, 1600))
                image_file = io.BytesIO()
                copy.convert('RGB').save(image_file, format='JPEG', quality=78, optimize=True)
                image_file.seek(0)
            open_files.append(image_file)

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

        return True

    except Exception as error:

        # Discord failure must never stop photography.

        print(
            f"Discord notification failed: {error}",
            flush=True
        )

        return False

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
                time.sleep(catcam_advanced.get("burst_interval"))

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



# ============================================================
# Background bird classification
# ============================================================

def bird_detection_worker():
    """Classify queued bursts and send only bird-positive images to Discord.

    No photos are deleted. Failed/incomplete classifications are preserved.
    """
    print("Bird detection worker started", flush=True)
    while True:
        try:
            with catcam_stats.connect() as conn:
                row = conn.execute("""
                    SELECT id, folder, photo_count, motion_percent, classification
                    FROM events
                    WHERE (classification='pending' AND photo_count > 0)
                       OR (classification='bird' AND discord_status='pending')
                    ORDER BY id LIMIT 1
                """).fetchone()
            if row is None:
                time.sleep(5)
                continue

            event_id, folder, expected_count, motion_percent, classification = row
            event_dir = Path(folder)

            if classification == 'pending':
                photos = sorted(event_dir.glob('*.jpg'))
                if len(photos) != expected_count:
                    catcam_stats.update_event(
                        event_id, classification='error',
                        error='Photograph count mismatch'
                    )
                    continue
                catcam_stats.update_event(event_id, classification='processing')
                print(f'Analyzing event {event_id}: {event_dir}', flush=True)
                # Classify photos in order, stopping immediately after the first bird.
                # Reuse the existing single-image Google Vision logic via detect_burst([photo]).
                # The original classifier handles API reservation and its own bird threshold.
                checked = []
                detected_photo = None
                classification_error = None
                for photo in photos:
                    result = bird_detection.detect_burst([photo])
                    catcam_stats.save_photo_detections(event_id, result['results'])
                    checked.extend(result['results'])
                    if not result['complete']:
                        classification_error = '; '.join(str(e.get('error', 'Vision error'))
                                                          for e in result.get('errors', [])) or 'Incomplete classification'
                        break
                    if result['classification'] == 'bird':
                        detected_photo = photo
                        break
                if classification_error:
                    catcam_stats.update_event(
                        event_id, classification='error',
                        bird_photo_count=sum(bool(r['bird_detected']) for r in checked),
                        error=classification_error
                    )
                    print(f'Event {event_id}: classification incomplete: {classification_error}', flush=True)
                    continue
                first_bird_photo = int(detected_photo.stem) if detected_photo else None
                bird_result = next((r for r in checked if detected_photo and
                                    Path(r['photo']) == detected_photo), None)
                labels = (bird_result.get('labels') or bird_result.get('bird_labels') or []) if bird_result else []
                # Google Vision labels may be strings or dictionaries depending on classifier.
                label_names = []
                for label in labels:
                    if isinstance(label, dict):
                        label_names.append(str(label.get('description') or label.get('name') or ''))
                    elif isinstance(label, (list, tuple)):
                        label_names.append(str(label[0]) if label else '')
                    else:
                        label_names.append(str(label))
                label_names = [s for s in label_names if s][:12]
                outcome = 'bird' if detected_photo else 'no_bird'
                catcam_stats.update_event(
                    event_id, classification=outcome,
                    bird_photo_count=1 if detected_photo else 0,
                    first_bird_photo=first_bird_photo,
                    bird_labels_json=json.dumps(label_names), error=None
                )
                print(f"Event {event_id}: {outcome} ({len(checked)}/{len(photos)} Vision calls)", flush=True)
                if outcome == 'no_bird':
                    catcam_stats.update_event(event_id, discord_status='not_needed')
                    print(f'Event {event_id}: Discord skipped (no birds)', flush=True)
                    continue

            # A bird-positive burst is preserved in full; send all six original photos.
            all_photos = sorted(event_dir.glob('*.jpg'))
            if len(all_photos) != 6:
                catcam_stats.update_event(event_id, discord_status='error',
                                          error='Bird burst does not contain six photos')
                continue
            detection = catcam_stats.get_event_details(event_dir)
            if not detection['first_bird_photo']:
                catcam_stats.update_event(event_id, discord_status='error',
                                          error='Confirmed bird photo number missing')
                continue
            if not catcam_advanced.get("discord_enabled") or not DISCORD_TOGGLE.exists():
                catcam_stats.update_event(event_id, discord_status='disabled')
                print(f'Event {event_id}: Discord disabled', flush=True)
                continue
            if not DISCORD_WEBHOOK_URL:
                catcam_stats.update_event(event_id, discord_status='failed')
                print(f'Event {event_id}: Discord webhook not configured', flush=True)
                continue

            try:
                event_timestamp = datetime.strptime(
                    f'{event_dir.parent.name}/{event_dir.name}',
                    '%Y-%m-%d/%H-%M-%S'
                )
            except ValueError:
                catcam_stats.update_event(event_id, discord_status='error',
                                          error='Invalid event folder timestamp')
                continue

            # Mark as sending first: a crash during upload may require manual review.
            catcam_stats.update_event(event_id, discord_status='sending')
            success = send_discord_notification(
                all_photos, event_dir, motion_percent or 0.0, event_timestamp,
                first_bird_photo=detection['first_bird_photo'],
                bird_labels=detection['bird_labels']
            )
            if success:
                catcam_stats.update_event(
                    event_id, discord_sent=1,
                    discord_photo_count=len(all_photos), discord_status='sent'
                )
            else:
                catcam_stats.update_event(event_id, discord_status='failed')
        except Exception as exc:
            print(f'Bird detection worker error: {exc}', flush=True)
            time.sleep(10)


def recover_interrupted_classifications():
    """
    Restore events interrupted by a service restart.

    They will be classified again. Previously submitted
    requests may be repeated, so API usage is reserved again.
    """
    with catcam_stats.connect() as conn:
        conn.execute("""
            UPDATE events
            SET classification = 'pending'
            WHERE classification = 'processing'
        """)


def start_bird_detection_worker():
    recover_interrupted_classifications()

    worker = threading.Thread(
        target=bird_detection_worker,
        daemon=True,
        name="CatCamBirdDetection"
    )

    worker.start()

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

        # Record every accepted capture trigger.
        # This persists even if photographs are later deleted.
        event_id = catcam_stats.record_trigger(
            trigger_source,
            changed_percent,
            event_dir
        )

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

        output_degrees = catcam_advanced.output_rotation()
        print(f"Orienting photographs ({output_degrees}° clockwise)...", flush=True)
        successes=0
        for photo in captured_photos:
            if rotate_photo(photo, output_degrees): successes+=1
        print(f"Orientation complete: {successes}/{len(captured_photos)} successful",flush=True)

        # Queue thumbnail generation only after the six originals are fully
        # written and rotated. The worker runs independently of capture and
        # Google Vision classification, so it does not delay either operation.
        if len(captured_photos) == BURST_COUNT and successes == BURST_COUNT:
            catcam_thumbnails.queue_event(event_dir)

        # The background worker picks up this event from SQLite.
        # Only complete, successfully rotated bursts are queued.
        if len(captured_photos) == BURST_COUNT and successes == BURST_COUNT:
            catcam_stats.update_event(
                event_id,
                photo_count=len(captured_photos),
                classification="pending"
            )
        else:
            catcam_stats.update_event(
                event_id,
                photo_count=len(captured_photos),
                classification="error",
                error="Incomplete capture or rotation failure"
            )

        # Discord is sent by the bird-detection worker after classification.
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

# Generate thumbnails in a separate thread after each completed capture.
catcam_thumbnails.start_worker()

# Start background Google Vision processing.
start_bird_detection_worker()
threading.Thread(
    target=catcam_cleanup.cleanup_worker,
    daemon=True,
    name="CatCamPhotoCleanup"
).start()

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
            changed_pixels=np.count_nonzero(diff>catcam_advanced.get("pixel_difference"))
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
            and now-last_trigger>=catcam_advanced.get("capture_cooldown")
            and catcam_advanced.get("motion_enabled")
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
        time.sleep(catcam_advanced.get("sample_interval"))

except KeyboardInterrupt:
    print("\nStopping wildlife camera.",flush=True)

finally:
    picam2.stop()
