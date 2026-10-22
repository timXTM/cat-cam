# CatCam — Raspberry Pi Wildlife Camera

**Documentation updated:** October 21, 2026 · **Code reviewed:** `timXTM/cat-cam`, commit `c549e5a`.

CatCam is a self-hosted bird-feeder camera running on a Raspberry Pi Zero W. It watches a configurable region of interest (ROI), captures six high-resolution JPEGs per motion/manual trigger, classifies the burst, and serves a LAN dashboard, galleries, and bird-activity analytics. Optional Discord delivery sends bird-positive bursts. The system can use Google Cloud Vision or an authenticated local detector on a separate Raspberry Pi 4.

> **Scope:** This repository contains the Pi Zero camera application, browser UI, and Pi 4 *client*. The Pi 4 AI server source code is included in [`pi-four/`](pi-four/). Large model weights, credentials, and the Syncthing deployment are not included. The addresses and paths below describe the current installation; they are not universal defaults.

## Features

- Live MJPEG preview, camera-health status, manual trigger, configurable motion ROI and threshold, focus/autofocus, and mounting orientation.
- Six full-resolution photographs per burst, thumbnail cache, and date/time-organized archive.
- Two detection engines: Google Cloud Vision and authenticated Pi 4 Local AI (YOLO bird detection with optional AIY Birds species identification).
- Photo-by-photo detection records, including checked photographs, first bird-positive photograph, species estimates, and confidence scores.
- English common names displayed alongside scientific names for AIY species identifications.
- Bird-positive bursts retained and optionally delivered to Discord with all six photographs.
- Conservative cleanup of fully classified non-bird bursts after the configured retention period.
- Dashboard, Settings, paginated Gallery, burst details, and Bird Activity analytics.
- Searchable species-confirmation dropdown with the ability to add new species.
- Persistent SQLite species catalog with case-insensitive duplicate prevention.
- Manual species confirmations stored separately from original AI estimates.
- Bird Activity identification-status filters: All, AI estimated, Manually confirmed, and Unidentified.
- Separate AI Estimate and Confirmed Species columns, plus identification-status summary counters.
- Shared navigation/header, camera-health indicators, and consistent light/dark theme.
- SQLite event history, photo-level detections, API usage, and species confirmations.

## Hardware and topology

| Component | Role | Current example |
| --- | --- | --- |
| Pi Zero W + Raspberry Pi camera | Capture, motion detection, HTTP UI, event database | `192.168.1.201:8080` |
| Pi 4 | External authenticated local AI server | `192.168.1.75:8765` |
| Shared/synchronized storage | Makes Pi Zero captures accessible to Pi 4 detector | `/mnt/494USB/CatCam Wildlife` on Pi 4 |
| LAN or trusted VPN browser | View Dashboard, Gallery, Bird Activity | `http://192.168.1.201:8080/` |

The local-AI client sends a relative burst path, ROI, confidence threshold, and species-identification preference. It does **not** upload six JPEGs in the HTTP request. Photos must already be accessible to the Pi 4 through the configured synchronized storage. The Pi 4 server is deployed separately; its source code and setup notes are available in [`pi-four/README.md`](pi-four/README.md).

## 3D-printed enclosure

The CatCam build uses a **3D-printed case from Thingiverse**: [Thingiverse design #4375297](https://www.thingiverse.com/thing:4375297).

The case is part of the physical build; its printable design files are not included in this software repository. Consult the Thingiverse listing for the original files, designer credit, printing guidance, and license. Check camera module fit, ribbon-cable clearance, and mounting orientation before assembly. The CatCam Settings page supports camera mounting orientation and image rotation adjustments.

*The Thingiverse listing was not accessible for verification during this README update, so exact print specifications and designer attribution are not asserted here.*

## Repository layout

| File | Purpose |
| --- | --- |
| [`pi-four/`](pi-four/) | Raspberry Pi 4 AI detection server, YOLO configuration, utilities, and installation documentation |
| `wildlife_camera.py` | Camera acquisition, ROI motion, six-photo capture, background workers, web server, Discord |
| `bird_detection.py` | Google Cloud Vision integration and bird-label detection |
| `catcam_local_ai.py` | Authenticated Pi 4 detection client; no silent Vision fallback |
| `catcam_advanced.py` | Validation and persistence of advanced settings |
| `catcam_stats.py` | SQLite schema, events, photo detections, Vision usage, species confirmation |
| `catcam_activity.py` | Event-based bird analytics, inferred types, hierarchical filters |
| `catcam_gallery.py` | Gallery discovery, filters, pagination |
| `catcam_cleanup.py` | Safe non-bird burst and thumbnail cleanup |
| `catcam_thumbnails.py` | Background thumbnail generation/cache |
| `catcam_dashboard.html` | Dashboard and Settings interface |
| `catcam_gallery.html` | Capture Gallery |
| `catcam_event.html` | Burst details, enlarged-photo viewer, species-confirmation form |
| `catcam_bird_activity.html` | Bird Activity charts and event listing |
| `catcam_bird_gallery.html` | Legacy bird gallery template (current `/bird-gallery` route uses main Gallery) |
| `catcam_header.css`, `catcam_header.js` | Shared navigation and camera-health header |
| `catcam.service` | Example systemd unit |
| `update.sh` | Guarded Git update, restart, and rollback helper |
| `requirements.txt` | Python dependency notes |
| `test_catcam_activity.py` | Bird Activity analytics and identification tests |
| `test_catcam_species.py` | Species catalog and manual confirmation tests |
| `install_catcam_bird_activity.py`, `install_catcam_bird_type_gallery.py` | Older installation/migration helpers, not the standard update path |

## Installation and operation on the Pi Zero

This repository does not provide a complete fresh-install script. Configure Raspberry Pi OS, the camera, network, credentials, and systemd separately. Install Picamera2 through Raspberry Pi OS packages rather than treating it as an ordinary pip-only dependency:

```bash
sudo apt update
sudo apt install python3-picamera2 python3-numpy python3-requests python3-pil
```

The current systemd service runs as user `pi`, with working directory `/home/pi`, command `/usr/bin/python3 /home/pi/catcam/wildlife_camera.py`, and environment file `/etc/catcam.env`. Protect that file and keep all credentials out of Git.

For an existing deployment, commit/push changes from the development machine, then:

```bash
cd /home/pi/catcam
git status --short
git pull --ff-only
python3 -m py_compile wildlife_camera.py catcam_stats.py catcam_activity.py
sudo systemctl restart catcam.service
sudo systemctl status catcam.service --no-pager
sudo journalctl -u catcam.service -n 100 --no-pager
```

Alternatively, `./update.sh` fetches `origin/main`, rejects a dirty working tree, fast-forwards, compiles the main Python file, restarts, and attempts a rollback on failure. Read it before use: its rollback uses `git reset --hard` after first checking for local modifications.

## Storage and configuration

| Path on Pi Zero | Content |
| --- | --- |
| `/home/pi/wildlife/YYYY-MM-DD/HH-MM-SS/01.jpg` … `06.jpg` | Original burst images |
| `/home/pi/catcam_data/catcam_stats.db` | SQLite event/label/usage/confirmation history |
| `/home/pi/catcam_data/thumbnails/` | Thumbnail cache |
| `/home/pi/catcam_settings.json` | Basic ROI, threshold, and focus settings |
| `/home/pi/catcam_advanced_settings.json` | Advanced persistent settings |
| `/home/pi/.catcam-discord` | File-presence toggle for Discord sending |
| `/home/pi/catcam_local_ai_token` | Secret token for Pi 4 API |
| `/home/pi/.config/catcam/vision-credentials.json` | Google Vision credentials, if used |
| `/etc/catcam.env` | Service environment, including `DISCORD_WEBHOOK_URL` |

Advanced settings cover motion enablement, pixel difference, sampling/cooldown/burst intervals, Discord/cleanup switches, retention and cleanup cadence, thumbnail/preview parameters, mounting orientation and rotation, default gallery filter, Google Vision starting photo, detection engine, Pi 4 host/port/photo root/confidence/species toggle/timeout, and IANA timezone. Defaults and validation are defined in `catcam_advanced.py`.

**Back up the SQLite database and settings files separately.** Git does not version or roll back runtime data.

## Capture and classification pipeline

1. The camera samples frames and checks motion within the configured ROI; a manual trigger is also supported.
2. A trigger records an event and captures six high-resolution images.
3. The detection worker uses the engine recorded for the event:
   - **Google Vision:** starts with the configured image number, wraps around the burst, and stops on the first bird-positive label result. Successful photo-level results are recorded. The hard-coded budget is **900 requests per calendar month** (`MONTHLY_API_LIMIT` in `catcam_stats.py`).
   - **Local AI:** calls the authenticated Pi 4 endpoint with the synchronized burst path and ROI. A bird result may include the detected photo, AIY species estimate, and confidence. Errors are **not** silently retried through Google Vision.
4. Bird-positive bursts are preserved and optionally sent to Discord as all six originals. Non-bird bursts do not generate Discord bird notifications.
5. A cleanup worker periodically deletes eligible fully classified non-bird bursts after the retention interval (default 24 hours; default check interval 15 minutes).

Incomplete or failed classification must not be treated as `no_bird`. Cleanup requires a `no_bird` event, six expected photos, six recorded negative photo detections, and strict path/content validation. To preview candidates without deleting anything:

```bash
cd /home/pi/catcam
python3 catcam_cleanup.py --dry-run
```

The Discord file toggle is enabled with `touch /home/pi/.catcam-discord` and disabled with `rm -f /home/pi/.catcam-discord`; the advanced Discord setting and configured webhook must also permit delivery.

## Species identification and manual confirmation

CatCam distinguishes automated species estimates from human-confirmed identifications.

### Automated identification

- Google Vision labels are interpreted using the species and broader-category rules in `catcam_activity.py`.
- Local AI can return an AIY scientific species name and confidence score.
- Known scientific names are translated to English common names using CatCam's species aliases.
- The original AI estimate remains stored even when a person confirms a different species.
- Automated predictions are estimates, not verified identifications.

### Manual confirmation

Open a bird-positive burst's Event Details page to confirm its species.

1. Select a species using the searchable dropdown.
2. If the species is missing, select **Add new species**.
3. Enter the new species name and save it to the catalog.
4. Select the species and confirm the identification.

Adding a new species does not automatically confirm the current burst.

Species added by users are stored in the SQLite `species_catalog` table and remain available for future confirmations. The catalog combines built-in species with user-added entries.

Confirmations are saved per burst, not per photograph. They can be changed or cleared.

CatCam stores `confirmed_species` and `species_status` separately from the original AI estimate. A confirmed species takes precedence in Gallery and Bird Activity displays, while the original estimate remains available for comparison.

Only bird-positive events can receive manual confirmations. Unknown species must first be added to the catalog. Invalid species names, including names containing control characters, are rejected.

Saving or clearing a confirmation does not rerun detection, modify photographs, or consume Google Vision requests.

### Bird Activity identification status

Bird Activity includes an Identification Status filter:

- **All:** All matching bird-positive events.
- **AI estimated:** A species estimate exists without manual confirmation.
- **Manually confirmed:** A person has confirmed the species.
- **Unidentified:** No species estimate or confirmation is available.

The Bird Type filter remains available and uses the best identification: human confirmation when present, otherwise the automated estimate.

The event table includes separate AI Estimate and Confirmed Species columns, allowing the original prediction to remain visible.

Summary counters distinguish confirmed, estimated, and unidentified events. Counts represent capture events (bursts), not individual photographs or unique bird visits.

## Web interface and API

| Route | Function |
| --- | --- |
| `/`, `/?tab=dashboard` | Dashboard, camera preview, controls |
| `/?tab=settings` | Settings, detection engine, conditional Vision usage |
| `/gallery` | Paginated historical Gallery |
| `/event?date=YYYY-MM-DD&event=HH-MM-SS` | Burst detail and enlarged-photo viewer |
| `/bird-activity` | Bird Activity charts |
| `GET /api/status` | Camera health; `camera_live` true when a frame was captured within 90 seconds |
| `GET /api/statistics` | Event and API usage statistics |
| `GET /api/gallery` | Gallery events, pagination, filters |
| `GET /api/bird-activity` | Event-based bird analytics |
| `GET /api/advanced-settings` | Read advanced settings |
| `POST /api/advanced-settings` | Update advanced settings |
| `POST /settings` | Save basic camera settings |
| `POST /trigger` | Manual capture request |
| `GET /api/species-options` | List available species, including user-added entries |
| `POST /api/species-add` | Add a species to the persistent SQLite catalog |
| `POST /api/species-confirmation` | Set or clear species for a bird-positive burst |
| `/stream.mjpg` | Live MJPEG |
| `/photo/...`, `/thumb/...` | Full JPEG and cached thumbnail |

Gallery query parameters: `mode=all|bird|no_bird`, `bird_type`, `start`, `end`, `start_hour`, `end_hour`, `order=newest|oldest`, `page`. Default page size is 20.

Bird Activity query parameters: `start`, `end` (`YYYY-MM-DD`), optional `start_hour`, `end_hour` (0–23, including overnight ranges), and `bird_type`. The response includes `total_events`, `by_hour`, `by_day`, `by_bird_type`, `available_bird_types`, and matching events. Broader filters such as `Cardinal` may include more specific types such as `Northern cardinal`.

**Metric definition:** A bird-positive capture event counts **one burst**, not six photos, not the number of bird labels, and not necessarily one unique bird visit. Repeated triggers can create multiple events.

Species confirmation request body:

```json
{"date":"2026-10-21","event":"18-59-45","species":"Northern Cardinal"}
```

Send JSON to `POST /api/species-confirmation`. Set `"species": null` to clear a confirmation. The capture must exist and its event must be classified as `bird`.


### Species catalog API

`GET /api/species-options` returns the available species for the searchable confirmation dropdown.

`POST /api/species-add` accepts a JSON object containing a species name.

Example request body:

    {"species": "Purple finch"}

User-added species persist in SQLite and are available for future confirmations. Adding a species does not automatically confirm the current event.

### Identification-status filtering

`GET /api/bird-activity` supports the existing date, hour, and bird-type filters, plus the optional `identification_status` parameter.

Accepted values:

- `confirmed` — manually confirmed species.
- `estimated` — AI-estimated species without manual confirmation.
- `unidentified` — no species estimate or confirmation.

Omit the parameter to include all identification statuses.

The Bird Activity response includes identification-status summary counts and separate AI-estimated and confirmed species information.

**Timezone caveat:** Gallery display supports the configurable IANA timezone, but Bird Activity analytics currently use `America/New_York` in `catcam_activity.py`, and Gallery interprets folder names initially in that timezone. Changing the display timezone is not yet a full system-wide timezone migration.

## Tests and troubleshooting

### Automated test coverage

The current automated suites contain 17 tests:

- 9 Bird Activity tests covering analytics, species estimates, confirmations, and identification-status filtering.
- 8 species tests covering the persistent catalog, duplicates, validation, confirmations, and clearing confirmations.

The species tests use temporary SQLite databases rather than the production database.

### Configurable database path

The production SQLite database defaults to:

    /home/pi/catcam_data/catcam_stats.db

For isolated testing, set the `CATCAM_STATS_DB_PATH` environment variable before importing `catcam_stats.py`.

This override is intended for testing and controlled deployments. Do not change the production database path without planning a data migration.

### Validation limitations

Unit tests and static JavaScript checks do not replace live browser, HTTP, camera, Discord, or Pi 4 integration testing.


```bash
cd /home/pi/catcam
python3 -m unittest -v test_catcam_activity.py test_catcam_species.py
python3 -m py_compile wildlife_camera.py bird_detection.py catcam_local_ai.py catcam_stats.py catcam_activity.py catcam_gallery.py catcam_cleanup.py catcam_advanced.py
curl -sS http://192.168.1.201:8080/api/status
curl -sS 'http://192.168.1.201:8080/api/gallery?mode=bird&page=1'
sudo journalctl -u catcam.service -n 100 --no-pager
```

Check Pi 4 local-AI health with the shared token (the unauthenticated endpoint can return `Unauthorized`):

```bash
TOKEN=$(cat /home/pi/catcam_local_ai_token)
curl -sS --max-time 10 -H "X-CatCam-Token: $TOKEN" http://192.168.1.75:8765/health
unset TOKEN
```

- **Camera offline/checking:** inspect `GET /api/status`, service logs, and camera initialization. The shared header uses recent camera frames, not an extra camera stream.
- **Gallery missing photos:** non-bird originals may have been removed by retention; thumbnails do not substitute for originals.
- **No Discord notification:** check event classification, advanced Discord toggle, `/home/pi/.catcam-discord`, environment webhook, and logs.
- **Pi 4 detection failure:** verify service, matching tokens, synchronized files, network, and timeout; do not interpret failure as a negative detection.
- **Unexpected species:** review AI confidence, per-photo labels, and human confirmation. Predictions are not verified identifications.
- **Update blocked:** inspect `git status --short` before pulling; avoid overwriting local edits.

## Security and limitations

- Designed for a **trusted LAN or VPN**, **not public internet exposure**. The web server has no application-level login or authorization for settings, manual trigger, or species-confirmation writes.
- Do not commit webhook URLs, service-account credentials, tokens, photo archives, or the runtime database.
- Pi 4 server source code and setup notes are included in `pi-four/`; model installation and Syncthing configuration remain external.
- Changing detection settings does not automatically reprocess historical bursts.
- Existing unit tests focus on Bird Activity logic; hardware capture, browser UI, Discord, and Pi 4 integration require separate end-to-end testing.
