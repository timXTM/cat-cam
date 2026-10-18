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

### Bird detection and Discord notifications

- Background bird detection using Google Cloud Vision Label Detection
- Individual photo classification and burst-level results: `bird`, `no_bird`, or `pending`
- Discord notifications for bird-positive bursts, including only photos classified as containing birds
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
