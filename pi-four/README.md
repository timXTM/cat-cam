# CatCam — Raspberry Pi 4 AI Detection Server

This directory contains the local AI detection components for CatCam.

The Raspberry Pi 4 serves as a dedicated bird-detection and species-identification
server for the Raspberry Pi Zero W camera.

## Architecture

1. The Pi Zero detects motion and captures a burst of six photographs.
2. Syncthing synchronizes the photographs to the Pi 4.
3. The Pi Zero sends a detection request to the Pi 4 over the local network.
4. The Pi 4 uses YOLOv4-tiny to detect birds.
5. The AIY Birds model attempts to identify the bird species.
6. Results are returned to the Pi Zero for classification, statistics,
   gallery display, and Discord notifications.

The Pi 4 does not receive image data directly through the API.
It reads photographs from its locally synchronized directory.

## Hardware

- Raspberry Pi 4
- External USB storage for photographs and AI models
- Raspberry Pi Zero W running the CatCam camera application

## Source Files

| File | Purpose |
|------|---------|
| server/bird_detector_server.py | Authenticated HTTP detection API |
| detect_and_identify.py | YOLO bird detection and AIY species identification |
| batch_yolo.py | Batch detection utility |
| test_bird.py | Detection testing utility |
| models/yolov4-tiny.cfg | YOLO model configuration |
| models/coco.names | COCO object classification labels |

## Software Dependencies

The application uses Python 3 and the following libraries:

- OpenCV
- NumPy
- Pillow

The AIY species-identification component also requires a compatible
TensorFlow Lite runtime.

Install dependencies in a Python virtual environment. Exact package
versions should be verified against the working Pi 4 installation.

## Model Files

Large model files are intentionally excluded from GitHub.

Expected YOLO model:

    /home/pi/bird-detector/models/yolov4-tiny.weights

Expected AIY model:

    /mnt/494USB/bird-models/aiy_birds_v1.tflite

Expected AIY labels:

    /mnt/494USB/bird-models/bird-labels.txt

The repository includes the YOLO configuration and COCO labels.

## Photograph Storage

Syncthing synchronizes photographs from the Pi Zero to:

    /mnt/494USB/CatCam Wildlife

The Pi 4 detection service reads images from this location.

## Authentication

The HTTP API uses a shared authentication token.

The server reads its token from:

    /home/pi/bird-detector/server/api_token

Requests must include the HTTP header:

    X-CatCam-Token

The token must be at least 32 characters long.

Never commit the token to GitHub.

## Network Configuration

Current Pi 4 address:

    192.168.1.75

Detection API port:

    8765

The server bind address can be configured using:

    CATCAM_AI_BIND

The Pi Zero communicates with the Pi 4 over the local network.

## Service

The application runs as a systemd service:

    catcam-local-ai.service

Useful commands:

    sudo systemctl status catcam-local-ai.service
    sudo systemctl restart catcam-local-ai.service
    journalctl -u catcam-local-ai.service -n 100 --no-pager

The service should run automatically when the Pi 4 starts.

## Repository Notes

This directory contains source code and small configuration files only.

The following are intentionally excluded:

- Authentication tokens and credentials
- Python virtual environments
- Large AI model files
- Captured photographs
- Generated detection results
- Temporary backups

The live Pi 4 installation currently resides at:

    /home/pi/bird-detector

This repository directory is a source-code backup and does not
automatically deploy changes to the running Pi 4.
