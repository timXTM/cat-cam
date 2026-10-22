import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BASE = Path("/mnt/494USB/CatCam Wildlife")
YOLO_MODELS = Path.home() / "bird-detector" / "models"
AIY_MODEL = "/mnt/494USB/bird-models/aiy_birds_v1.tflite"
AIY_LABELS = "/mnt/494USB/bird-models/bird-labels.txt"

# CatCam's previously recorded ROI on its 320x240 preview.
ROI = (57, 57, 254, 160)

def analyze_burst(folder, photo_base=None, confidence=0.25, roi=None, identify_species=True):
    base = Path(photo_base) if photo_base is not None else BASE
    directory = base / folder

    if not directory.is_dir():
        raise FileNotFoundError(str(directory))

    with open(YOLO_MODELS / "coco.names") as f:
        labels = [line.strip() for line in f]

    bird_id = labels.index("bird")

    yolo = cv2.dnn_DetectionModel(
        str(YOLO_MODELS / "yolov4-tiny.weights"),
        str(YOLO_MODELS / "yolov4-tiny.cfg")
    )
    yolo.setInputParams(
        size=(416, 416),
        scale=1/255,
        swapRB=True
    )

    start = time.time()
    photos_checked = 0

    for photo in sorted(directory.glob("*.jpg")):
        photos_checked += 1

        with Image.open(photo) as original:
            image = original.transpose(Image.Transpose.ROTATE_270)
            w, h = image.size
            x1, y1, x2, y2 = roi if roi is not None else ROI

            crop = image.crop((
                round(x1 * w / 320),
                round(y1 * h / 240),
                round(x2 * w / 320),
                round(y2 * h / 240),
            )).convert("RGB")

            frame = cv2.cvtColor(
                np.asarray(crop),
                cv2.COLOR_RGB2BGR
            )

        classes, confidences, boxes = yolo.detect(
            frame,
            confThreshold=float(confidence),
            nmsThreshold=0.4
        )

        birds = [
            float(conf)
            for cls, conf in zip(
                np.asarray(classes).flatten(),
                np.asarray(confidences).flatten()
            )
            if int(cls) == bird_id
        ]

        if not birds:
            continue


        # YOLO found a bird. Run AIY only when enabled.
        if not identify_species:
            return {
                "classification": "bird",
                "photo": photo.name,
                "photos_checked": photos_checked,
                "yolo_confidence": round(max(birds), 4),
                "species": None,
                "species_score": None,
                "elapsed_seconds": round(time.time() - start, 2),
            }

        completed = subprocess.run(
            [
                str(Path.home() / "bird-classifier/venv/bin/python"),
                str(Path.home() / "bird-classifier/identify.py"),
                str(photo),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        identification = json.loads(completed.stdout)

        return {
            "classification": "bird",
            "photo": photo.name,
            "photos_checked": photos_checked,
            "yolo_confidence": round(max(birds), 4),
            "species": identification["species"],
            "species_score": identification["species_score"],
            "elapsed_seconds": round(time.time() - start, 2),
        }

    return {
        "classification": "no_bird",
        "photo": None,
        "photos_checked": photos_checked,
        "species": None,
        "elapsed_seconds": round(time.time() - start, 2),
    }

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python detect_and_identify.py YYYY-MM-DD/HH-MM-SS")
        sys.exit(1)

    result = analyze_burst(sys.argv[1])
    print(json.dumps(result, indent=2))
