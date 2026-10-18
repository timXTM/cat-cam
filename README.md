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
- Browser-based photo gallery
- Persistent camera settings
- Automatic startup through `systemd`

### Bird detection and Discord notifications

- Background bird detection using Google Cloud Vision Label Detection
- Individual photo classification and burst-level results: `bird`, `no_bird`, or `pending`
- Discord notifications for bird-positive bursts, including only photos classified as containing birds
- No Discord notification for bursts classified as having no birds
- Photos remain stored locally regardless of their classification
- Monthly Google Vision request budget of **900 images**, tracked in SQLite

**Note:** Bird detection is not the same as reliable species identification. Species-level statistics are not yet implemented. Bird-positive Discord delivery has been implemented, but a live bird-positive event has not yet been verified end-to-end.

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

**Implemented:** Camera capture, ROI motion detection, LAN controls and gallery, SQLite statistics, background Google Vision classification, bird-filtered Discord logic, and the statistics dashboard.

**Awaiting field verification:** A naturally occurring bird-positive event, including the exact images delivered to Discord.

**Not yet implemented:** Reliable bird species identification and species-level statistics; automatic deletion of no-bird photo bursts. **Automatic photo deletion is currently disabled.**
