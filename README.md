# CatCam

A Raspberry Pi wildlife camera that captures motion-triggered photo bursts, provides a local web dashboard, and uses Google Cloud Vision to identify bird-containing photos before sending Discord alerts.

## Hardware

- Raspberry Pi Zero W
- Arducam 12 MP IMX708 autofocus camera
- Raspberry Pi Zero camera ribbon cable
- 3D-printed enclosure: [Thingiverse design #4375297](https://www.thingiverse.com/thing:4375297)

## Features

### Camera and web interface

- Motion detection with an adjustable region of interest (ROI) and sensitivity threshold
- Six-photo bursts triggered by motion or a manual button
- Full-resolution 4608 × 2592 photographs
- Live camera preview on the local network
- Manual focus adjustment and continuous autofocus toggle
- Modern responsive LAN dashboard with Dashboard, Gallery, and Settings navigation, and individual capture pages
- Cached 420 × 420 maximum JPEG gallery thumbnails (quality 72); original full-resolution photos load only when enlarged
- Thumbnails are generated automatically in a background thread immediately after each successful six-photo capture, with on-demand fallback for older photos
- Persistent camera settings
- Automatic startup through `systemd`


### Physical mounting and output orientation

The camera module is currently mounted sideways to photograph a portrait-oriented scene. CatCam corrects the sensor image by rotating the live MJPEG preview and each **newly captured** full-resolution JPEG. The default is a **90° clockwise output rotation**, preserving the existing installation.

In **Settings → Camera mounting & image orientation**, select the physical mounting position: **normal (0°)**, **sideways clockwise (270°)**, **sideways counterclockwise (90°)**, or **upside down (180°)**. An advanced rotation override permits 0°, 90°, 180°, or 270° regardless of the mounting selection. These are output corrections, not physical camera controls. If a sideways selection produces an upside-down image, choose the opposite sideways position or override the rotation.

- To switch to landscape photography, **physically rotate the camera module** so its sensor is in landscape orientation, then select **Normal — landscape** (0°) and save.
- Changing orientation immediately updates the live preview and ROI overlay, and affects **future captures only**. Previously saved JPEGs and their cached thumbnails are not changed.
- Motion ROI coordinates remain in the **native, unrotated 320×240 sensor frame**. The dashboard transforms the overlay and drag/resize coordinates to match 0°, 90°, 180°, or 270° previews. Changing output rotation does not change the region monitored by motion detection.
- For each six-photo burst, the selected rotation is read once after the burst completes and is applied consistently to all six photographs. At 0°, no JPEG transformation is needed. At 90°, 180°, or 270°, `jpegtran` rotates the saved JPEGs before thumbnails or bird classification are queued.
- Output aspect ratio is landscape (4:3 live preview) at 0°/180° and portrait (3:4) at 90°/270°. Saved full-resolution files have correspondingly swapped dimensions when rotated by 90°/270°.
- Orientation preferences are persisted in `/home/pi/catcam_advanced_settings.json`; the browser's **Portrait/Wide layout** switch is separate and does not rotate images.

**Safety:** Changing mounting/rotation during an active capture is discouraged. Test the live preview and manually trigger a new capture after remounting. The preview and capture rotation are software transformations; they do not change lens field of view or camera sensor orientation.

Reference: [Raspberry Pi Picamera2 manual](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf).

### Bird detection and Discord notifications

- Background bird detection using Google Cloud Vision Label Detection
- Sequential photo classification that stops at the first confirmed bird; burst-level results: `bird`, `no_bird`, or `pending`
- Discord notifications for bird-positive bursts, including all six photos (Discord-sized copies)
- No Discord notification for bursts classified as having no birds
- Bird-containing bursts are retained; fully classified non-bird bursts are eligible for automatic cleanup after 24 hours
- Monthly Google Vision request budget of **900 images**, tracked in SQLite

**Note:** Bird detection is not the same as reliable species identification. Species-level statistics are not yet implemented. Bird-positive Discord delivery has been implemented, but a live bird-positive event has not yet been verified end-to-end.

### Automatic non-bird photo cleanup

The `catcam_cleanup.py` module provides a conservative **24-hour retention policy** for non-bird bursts. When the updated application is deployed and its service restarted, a background worker checks for eligible bursts every **15 minutes**.

A burst is eligible only when:

- The event is at least **24 hours old** and classified as `no_bird`.
- All **six** expected photographs have individual database classifications of **no bird**.
- The event is not already marked as deleted.
- The burst directory is in the expected `/home/pi/wildlife/YYYY-MM-DD/HH-MM-SS/` location, contains exactly `01.jpg` through `06.jpg`, and passes path and file safety checks.

**Retained:** Any burst containing a bird, awaiting classification, having incomplete/failed classification, or failing a safety check. The cleanup removes eligible JPEG files and their now-empty burst folder **and the corresponding cached thumbnails**. It **preserves SQLite event and photo-classification records** for the dashboard. If thumbnail deletion fails, the original photo deletion and database record remain authoritative; the failure is logged.

Preview eligible deletions without deleting anything:

```bash
cd /home/pi/catcam
python3 catcam_cleanup.py --dry-run
```

The cleanup worker starts when CatCam starts; merely committing or pulling these files does **not** activate it until the running service is restarted. Run the dry-run and review its output before restarting to enable cleanup.

**Syncthing warning:** If your photo folder is synchronized to another device, deletion on the Pi may propagate to that device. Confirm your Syncthing configuration and backups before enabling cleanup.

### Thumbnail generation and retention

Gallery pages serve lightweight JPEG thumbnails rather than transferring full-resolution images. The full-resolution original is requested **only when a photo is enlarged**.

- After each **complete, successfully rotated six-photo burst**, CatCam queues thumbnail generation in a separate background thread. This avoids holding up camera capture or Google Vision classification.
- Each thumbnail is limited to **420 × 420 pixels**, with aspect ratio preserved, saved as a JPEG at **72% quality**.
- Cached previews mirror the original folder structure: `/home/pi/catcam_data/thumbnails/YYYY-MM-DD/HH-MM-SS/01.jpg` through `06.jpg`.
- Thumbnails are generated **on demand** if they are missing or outdated, including for historical photos. The cache is reused on subsequent visits.
- The existing conservative cleanup worker removes the **six matching cached thumbnails** after it successfully deletes an eligible six-photo non-bird burst at least 24 hours old. Bird-positive, pending, incomplete, or otherwise ineligible bursts and their thumbnails are retained.
- The cleanup worker does not recursively erase the thumbnail cache. Unexpected files or symlinks are not intentionally deleted.
- Thumbnails are disposable cache files; deleting the thumbnail cache manually does not delete or modify original photographs. Cached previews will be regenerated as needed.

Check the cache size and file count:

```bash
du -sh /home/pi/catcam_data/thumbnails/
find /home/pi/catcam_data/thumbnails/ -type f | wc -l
```

**Deployment note:** Update `wildlife_camera.py`, `catcam_cleanup.py`, and add `catcam_thumbnails.py` together before restarting CatCam. Existing thumbnail files are reused; no migration or photo reprocessing is required. If the service restarts during thumbnail generation, the on-demand gallery fallback will generate missing previews later.

### Statistics dashboard

The LAN webpage includes a statistics panel with:

- Total, motion, and manual triggers
- Bird, non-bird, and pending events
- Bird-positive photograph counts
- Discord notification counts
- Deleted-event statistics
- Google Vision monthly request usage and progress toward the 900-image budget
- Recent event activity, including classification and Discord status

Statistics refresh automatically approximately every 30 seconds. Event and photo-classification records are stored in SQLite and survive service restarts.

## Project files

| File | Purpose |
| --- | --- |
| `wildlife_camera.py` | Camera capture, motion detection, LAN webpage, background worker, and Discord integration |
| `bird_detection.py` | Google Cloud Vision bird classification |
| `catcam_stats.py` | SQLite event, photo, and API usage tracking |
| `catcam_cleanup.py` | Conservative 24-hour cleanup of fully classified non-bird bursts and their thumbnails |
| `catcam_thumbnails.py` | Background and on-demand JPEG thumbnail generation, caching, and cache deletion |
| `catcam_dashboard.html` | Responsive dashboard, gallery, and settings interface |
| `catcam_event.html` | Individual six-photo capture viewer with full-resolution enlargement |
| `catcam.service` | `systemd` service definition |
| `update.sh` | Update from GitHub and restart the service |
| `requirements.txt` | Python dependency list |

## Installation and dependencies

Install the Raspberry Pi OS packages needed for the camera and image processing:

```bash
sudo apt update
sudo apt install python3-picamera2 python3-numpy python3-requests python3-pil
```

Bird detection also requires the Python dependencies used by `bird_detection.py`, including Google authentication libraries, and an enabled Google Cloud Vision API project. Check `requirements.txt` and the deployed Python environment before installation.

For the IMX708 camera, the following configuration may be needed in `/boot/firmware/config.txt`:

```ini
camera_auto_detect=0
dtoverlay=imx708
```

Reboot after changing the camera configuration.

The application is deployed at `/home/pi/catcam/`, and its service definition is installed at `/etc/systemd/system/catcam.service`.

## Configuration and data locations

| Path | Description |
| --- | --- |
| `/home/pi/catcam_settings.json` | Camera and motion settings |
| `/home/pi/wildlife/` | Captured photographs, organized by date and burst |
| `/home/pi/catcam_data/thumbnails/` | Disposable cached JPEG previews, organized by date and burst |
| `/home/pi/catcam_data/catcam_stats.db` | Persistent SQLite statistics and classifications |
| `/etc/catcam.env` | Discord webhook environment configuration |
| `/home/pi/.config/catcam/vision-credentials.json` | Google Cloud service account credentials |

The Discord webhook is supplied through the `DISCORD_WEBHOOK_URL` environment variable. The Google Cloud credentials file must remain private.

**Never commit credentials, webhook URLs, the SQLite database, local settings, or captured photographs to GitHub.**

## LAN dashboard

On the local network, open:

```text
http://<raspberry-pi-ip>:8080/
```

The dashboard includes the live preview, camera controls, gallery, and statistics. The interface is intended for LAN or private VPN access; do not expose it directly to the public internet without additional security.

## Updating CatCam

On the Raspberry Pi, run:

```bash
/home/pi/catcam/update.sh
```

The update script retrieves changes from GitHub and restarts CatCam when updates are available. **Commit and push local changes before running it** to avoid conflicts or overwriting work that exists only on the Pi.

## Service management

```bash
sudo systemctl restart catcam.service
systemctl status catcam.service --no-pager
journalctl -u catcam.service -n 50 --no-pager
```

## Current status and planned improvements

**Implemented in code:** Camera capture, ROI motion detection, modern LAN dashboard and gallery, cached thumbnails generated after capture and on demand, SQLite statistics, background Google Vision classification, bird-filtered Discord logic, statistics dashboard, and 24-hour non-bird cleanup of both originals and thumbnails. **New code must be pulled and the Pi service restarted before the thumbnail changes take effect.**

**Awaiting field verification:** A naturally occurring bird-positive event, including the exact images delivered to Discord.

**Not yet implemented:** Reliable bird species identification and species-level statistics.

## Expanded settings page (October 2026)

The Settings tab groups controls into **Camera & focus**, **Motion detection**, **Capture timing**, **Bird detection & notifications**, **Storage & cleanup**, **Thumbnails & live preview**, **Appearance**, and **Protected system settings**.

The dashboard continues to provide live ROI editing, motion percentage threshold, autofocus, and manual focus. The Settings tab adds these **persistent, live-adjustable** controls:

| Group | Settings | Default |
| --- | --- | --- |
| Motion detection | Enable automatic motion capture; pixel difference threshold; motion sampling interval; cooldown | On; 20; 0.25 s; 5 s |
| Capture timing | Delay between photos in a six-photo burst | 0.4 s |
| Notifications | Enable/disable Discord alerts | On (also requires existing Pi-side toggle and webhook) |
| Storage & cleanup | Enable cleanup; non-bird retention; cleanup check interval | On; 24 h; 15 min |
| Thumbnails | Maximum thumbnail dimension; JPEG quality | 420 px; 72 |
| Live preview | Browser MJPEG frame interval | 0.5 s |

Advanced settings are saved atomically in `/home/pi/catcam_advanced_settings.json` and validated on the server. The original ROI/focus settings remain in `/home/pi/catcam_settings.json`. Settings persist through service restarts. The advanced settings page has Save, Discard, and Restore Defaults controls. Restoring defaults requires confirmation.

**Safety constraints:** The burst count stays fixed at six, because database classification and deletion safety checks currently require exactly six images. The Google Vision monthly API quota and bird-only Discord filter remain fixed; credentials are not shown in the browser. Photo orientation is fixed. The thumbnail size/quality controls affect newly generated thumbnails; existing cached thumbnails are reused. Reducing retention may make previously classified non-bird bursts immediately eligible for deletion at the next cleanup pass, including synchronized deletions via Syncthing. Disabling motion capture does not disable manual capture. Disabling Discord notifications does not disable classification. Disabling cleanup does not delete anything. Changes to cleanup check interval take effect after the current worker sleep finishes.

**Deployment:** Copy `wildlife_camera_settings.py` to `wildlife_camera.py`, `catcam_cleanup_settings.py` to `catcam_cleanup.py`, `catcam_thumbnails_settings.py` to `catcam_thumbnails.py`, `catcam_dashboard_settings.html` to `catcam_dashboard.html`, and add `catcam_advanced.py`. Update this README. Commit/push, then on the Pi run `git pull --ff-only origin main` and `python3 -m py_compile wildlife_camera.py catcam_advanced.py catcam_cleanup.py catcam_thumbnails.py` before restarting `catcam.service`.


## Contextual Settings help and sources (October 2026)

The Settings tab includes expandable **ⓘ What does this setting do?** explanations for each advanced setting, plus Camera & focus, Appearance, and Protected system settings. Each explanation describes the effect **in CatCam**, and links to a relevant technical reference in a new browser tab. Explanations are embedded locally in `catcam_dashboard.html`, so viewing help does not require an internet connection; opening the external reference does. No Python modules, API endpoints, capture settings, or deletion rules are changed by this documentation-only update.

Primary references:

- Raspberry Pi Picamera2 manual (focus, lens position, camera controls): https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
- OpenCV image thresholding concepts (motion pixel threshold): https://docs.opencv.org/4.x/db/d8e/tutorial_threshold.html
- Python time module (timing concepts): https://docs.python.org/3/library/time.html
- Discord webhooks: https://discord.com/developers/docs/resources/webhook
- Pillow thumbnail and JPEG documentation: https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.thumbnail and https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#jpeg
- Google Cloud Vision quotas: https://docs.cloud.google.com/vision/quotas
- CatCam implementation-specific behavior: https://github.com/timXTM/cat-cam

**Note:** Generic references explain underlying concepts, not necessarily CatCam's exact algorithms. For instance, CatCam's monthly 900-call limit is an application-level safety limit, not a Google Cloud quota.


## Google Vision optimization: stop after first bird

For each new six-photo burst, CatCam checks photos in chronological order (01.jpg to 06.jpg) using Google Cloud Vision. **As soon as one photo is classified as containing a bird, the remaining photos are not submitted to Vision.** The entire burst is marked `bird` and all six original photos and thumbnails are preserved. A burst is classified `no_bird` only if all six photos are successfully checked with no bird detected; this preserves the conservative automatic deletion rule. Incomplete or errored classifications are never eligible for automatic deletion.

Discord receives **all six photos** for a bird-positive burst, with lightweight JPEG copies to avoid large webhook uploads. The original full-resolution images are unchanged. The message reads `Bird detected in photo X` and includes the bird-related labels available from the Google Vision classifier. Unchecked photos are not represented as individually confirmed bird-positive.

The main gallery and the individual burst page show the first bird-positive photo number and the classifier labels, where available. The individual page distinguishes checked-negative, checked-positive, and not-analyzed photos. Older events keep their existing classifications and may have no recorded first-bird photo or labels.

**Quota exhaustion behavior has not been changed in this update.** The existing 900-request monthly budget and current error/incomplete classification handling remain in place; improving quota exhaustion and backlog management is a separate future task.

### Deploying this change

Update these five files together: `wildlife_camera.py`, `catcam_stats.py`, `catcam_dashboard.html`, `catcam_event.html`, and `README.md`. Back up the SQLite database and current code before restarting. The database migration adds nullable `first_bird_photo` and `bird_labels_json` columns; existing records are not rewritten.
