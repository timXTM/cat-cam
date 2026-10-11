#!/bin/bash
set -euo pipefail

APP_DIR="/home/pi/catcam"
SERVICE="catcam.service"

cd "$APP_DIR"

echo "Checking for CatCam updates..."
git fetch origin main

CURRENT=$(git rev-parse HEAD)
LATEST=$(git rev-parse origin/main)

if [ "$CURRENT" = "$LATEST" ]; then
    echo "CatCam is already up to date."
    exit 0
fi

# Prevent overwriting local modifications.
if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: Local changes detected. Update cancelled."
    exit 1
fi

echo "Updating CatCam..."
git merge --ff-only origin/main

rollback() {
    echo "Update failed. Restoring previous version..."

    git reset --hard "$CURRENT"

    sudo systemctl restart "$SERVICE"

    if systemctl is-active --quiet "$SERVICE"; then
        echo "Previous CatCam version restored."
    else
        echo "WARNING: Previous version also failed to start."
    fi
}

echo "Validating Python syntax..."
if ! python3 -m py_compile wildlife_camera.py; then
    rollback
    exit 1
fi

echo "Restarting CatCam..."
if ! sudo systemctl restart "$SERVICE"; then
    rollback
    exit 1
fi

sleep 5

if systemctl is-active --quiet "$SERVICE"; then
    echo "CatCam updated successfully."
    echo "Version: $(git rev-parse --short HEAD)"
else
    rollback
    exit 1
fi
