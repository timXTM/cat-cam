import csv
import time
from pathlib import Path

import cv2
from PIL import Image
import numpy as np

BASE = Path("/mnt/494USB/CatCam Wildlife")
MODEL_DIR = Path.home() / "bird-detector" / "models"
OUTPUT = Path.home() / "bird-detector" / "yolo_results.csv"

ROI = (57, 57, 254, 160)

BURSTS = {
    "2026-10-20/07-34-05": False,
    "2026-10-20/06-57-32": False,
    "2026-10-18/00-43-28": False,
    "2026-10-19/22-02-36": False,
    "2026-10-20/20-07-23": False,
    "2026-10-20/18-59-45": True,
    "2026-10-20/15-58-03": True,
    "2026-10-20/15-53-23": True,
    "2026-10-20/09-35-37": True,
    "2026-10-18/17-45-01": True,
    "2026-10-20/09-43-41": False,
    "2026-10-20/14-10-27": True,
}

with open(MODEL_DIR / "coco.names") as f:
    labels = [line.strip() for line in f]

bird_id = labels.index("bird")

model = cv2.dnn_DetectionModel(
    str(MODEL_DIR / "yolov4-tiny.weights"),
    str(MODEL_DIR / "yolov4-tiny.cfg")
)
model.setInputParams(
    size=(416, 416),
    scale=1/255,
    swapRB=True
)

rows = []
start = time.time()

for folder, actual_bird in BURSTS.items():
    directory = BASE / folder

    if not directory.is_dir():
        print("MISSING:", directory)
        continue

    print("\n", folder, "BIRD" if actual_bird else "EMPTY")

    for photo in sorted(directory.glob("*.jpg")):
        with Image.open(photo) as original:
            image = original.transpose(Image.Transpose.ROTATE_270)
            w, h = image.size
            x1, y1, x2, y2 = ROI

            crop = image.crop((
                round(x1 * w / 320),
                round(y1 * h / 240),
                round(x2 * w / 320),
                round(y2 * h / 240),
            ))

            frame = cv2.cvtColor(
                np.asarray(crop.convert("RGB")),
                cv2.COLOR_RGB2BGR
            )

        classes, confidences, boxes = model.detect(
            frame,
            confThreshold=0.25,
            nmsThreshold=0.4
        )

        birds = [
            float(conf)
            for cls, conf in zip(np.asarray(classes).flatten(), np.asarray(confidences).flatten())
            if int(cls) == bird_id
        ]

        confidence = max(birds, default=0.0)

        rows.append({
            "folder": folder,
            "actual_bird": actual_bird,
            "photo": photo.name,
            "birds_detected": len(birds),
            "confidence": confidence,
        })

        print(
            f"  {photo.name}: "
            f"{len(birds)} birds, "
            f"confidence {confidence:.1%}"
        )

with open(OUTPUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

print("\nBURST SUMMARY")

tp = fp = tn = fn = 0

for folder, actual in BURSTS.items():
    burst_rows = [r for r in rows if r["folder"] == folder]

    if not burst_rows:
        continue

    best = max(r["confidence"] for r in burst_rows)
    predicted = best >= 0.25

    if predicted and actual:
        tp += 1
    elif predicted and not actual:
        fp += 1
    elif not predicted and actual:
        fn += 1
    else:
        tn += 1

    print(
        f"{folder} | "
        f"{'BIRD' if actual else 'EMPTY'} | "
        f"{'DETECTED' if predicted else 'NOT DETECTED'} | "
        f"{best:.1%}"
    )

print("\nRESULTS")
print(f"TP={tp}, FP={fp}, TN={tn}, FN={fn}")
print(f"Elapsed: {time.time() - start:.1f} seconds")
print("CSV saved:", OUTPUT)
