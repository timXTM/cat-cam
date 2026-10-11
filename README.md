# CatCam

A Raspberry Pi wildlife camera with motion detection, a web interface, and Discord notifications.

## Hardware

- Raspberry Pi Zero W
- Arducam 12MP IMX708 autofocus camera
- Raspberry Pi Zero camera ribbon cable

## Features

- Motion detection with adjustable region of interest (ROI)
- Adjustable motion sensitivity
- Six-photo bursts triggered by motion
- Manual photo triggering
- Full-resolution 4608 × 2592 photographs
- Live camera preview
- Manual focus adjustment
- Continuous autofocus toggle
- Discord notifications
- Web-based photo gallery
- Persistent camera settings
- Automatic startup using systemd

## Dependencies

Install the required Raspberry Pi OS packages:

    sudo apt update
    sudo apt install python3-picamera2 python3-numpy python3-requests python3-pil

## Camera configuration

The IMX708 camera requires these settings in `/boot/firmware/config.txt`:

    camera_auto_detect=0
    dtoverlay=imx708

Reboot after changing the camera configuration.

## Installation

The application is installed at:

    /home/pi/catcam/wildlife_camera.py

The systemd service is installed at:

    /etc/systemd/system/catcam.service

Local settings and photographs are stored outside the Git repository.

## Configuration

- Settings: `/home/pi/catcam_settings.json`
- Photographs: `/home/pi/wildlife/`
- Discord configuration: `/etc/catcam.env`

The Discord webhook is supplied through the `DISCORD_WEBHOOK_URL` environment variable.

Do not commit credentials, local settings, or photographs to GitHub.

## Updating CatCam

Run:

    /home/pi/catcam/update.sh

The update script downloads the latest version from GitHub and restarts CatCam when changes are available.

## Service management

Restart CatCam:

    sudo systemctl restart catcam.service

Check service status:

    systemctl status catcam.service

View recent logs:

    journalctl -u catcam.service -n 50 --no-pager
