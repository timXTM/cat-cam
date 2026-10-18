"""
CatCam Google Cloud Vision bird detection.

Uses Google's LABEL_DETECTION API.

- Maximum 900 requests per month.
- Records API usage in SQLite.
- Returns bird detection results.
- Never deletes photographs.
- Never sends Discord notifications.
"""

import os
import sys
import base64
import json
from pathlib import Path

import requests
import google.auth
from google.auth.transport.requests import Request

import catcam_stats


VISION_URL = "https://vision.googleapis.com/v1/images:annotate"

CREDENTIALS_PATH = (
    "/home/pi/.config/catcam/vision-credentials.json"
)

MAX_LABELS = 20

# Minimum confidence for a recognized bird label.
MIN_BIRD_CONFIDENCE = 0.50

# Bird-related labels, including some species-specific names.
BIRD_TERMS = {
    "bird",
    "birds",
    "songbird",
    "songbirds",
    "passerine",
    "avian",
    "cardinal",
    "carolina wren",
    "wren",
    "sparrow",
    "finch",
    "goldfinch",
    "chickadee",
    "titmouse",
    "blue jay",
    "jay",
    "woodpecker",
    "nuthatch",
    "robin",
    "hummingbird",
    "dove",
    "pigeon",
    "starling",
    "grackle",
    "oriole",
    "warbler",
    "thrush",
    "flycatcher",
    "kinglet",
    "bunting",
    "towhee",
    "junco",
}


class BirdDetectionError(Exception):
    """Raised when image classification cannot be completed."""


class MonthlyLimitReached(BirdDetectionError):
    """Raised when the monthly API allowance is exhausted."""


def is_bird_label(description):
    """Determine whether a Google label indicates a bird."""

    name = description.lower().strip()

    if name in BIRD_TERMS:
        return True

    # Recognize variations such as "Northern cardinal".
    # Match whole words to avoid unrelated substring matches.
    words = name.replace("-", " ").split()

    generic_terms = {
        "bird",
        "birds",
        "songbird",
        "songbirds",
        "passerine",
        "avian",
    }

    if any(word in generic_terms for word in words):
        return True

    # Recognize common bird-family and species labels.
    species_terms = {
        "cardinal",
        "wren",
        "sparrow",
        "finch",
        "chickadee",
        "titmouse",
        "woodpecker",
        "nuthatch",
        "robin",
        "hummingbird",
        "dove",
        "pigeon",
        "starling",
        "grackle",
        "oriole",
        "warbler",
        "thrush",
        "flycatcher",
        "kinglet",
        "bunting",
        "towhee",
        "junco",
    }

    return any(word in species_terms for word in words)


def get_credentials():
    """Load Google service-account credentials."""

    if not os.path.isfile(CREDENTIALS_PATH):
        raise BirdDetectionError(
            f"Credentials not found: {CREDENTIALS_PATH}"
        )

    credentials, project = google.auth.load_credentials_from_file(
        CREDENTIALS_PATH,
        scopes=[
            "https://www.googleapis.com/auth/cloud-platform"
        ],
    )

    credentials.refresh(Request())

    return credentials, project


def detect_bird(photo_path):
    """
    Analyze one photograph.

    Returns:
        {
            "photo": str,
            "bird_detected": bool,
            "bird_confidence": float,
            "bird_labels": list,
            "all_labels": list
        }

    Raises BirdDetectionError if classification fails.
    """

    photo_path = Path(photo_path)

    if not photo_path.is_file():
        raise BirdDetectionError(
            f"Photograph not found: {photo_path}"
        )

    # Authenticate before reserving a billable request.
    credentials, project = get_credentials()

    # Read image before reserving an API request.
    try:
        with open(photo_path, "rb") as f:
            image_content = base64.b64encode(
                f.read()
            ).decode("utf-8")
    except OSError as e:
        raise BirdDetectionError(str(e)) from e

    payload = {
        "requests": [{
            "image": {
                "content": image_content
            },
            "features": [{
                "type": "LABEL_DETECTION",
                "maxResults": MAX_LABELS
            }]
        }]
    }

    # Reserve one request atomically in SQLite.
    # Count it even if the network request subsequently fails.
    # This avoids undercounting requests Google may have received.
    if not catcam_stats.reserve_api_request():
        raise MonthlyLimitReached(
            "Monthly Google Vision limit reached"
        )

    try:
        response = requests.post(
            VISION_URL,
            headers={
                "Authorization": (
                    f"Bearer {credentials.token}"
                )
            },
            json=payload,
            timeout=60,
        )

        response.raise_for_status()

        data = response.json()

        annotations = data["responses"][0]

        if "error" in annotations:
            raise BirdDetectionError(
                annotations["error"].get(
                    "message", "Unknown API error"
                )
            )

    except (
        requests.RequestException,
        KeyError,
        IndexError,
        ValueError,
    ) as e:
        raise BirdDetectionError(str(e)) from e

    labels = []

    for label in annotations.get("labelAnnotations", []):
        labels.append({
            "name": label["description"],
            "confidence": label["score"],
        })

    bird_labels = [
        label for label in labels
        if (
            is_bird_label(label["name"])
            and label["confidence"] >= MIN_BIRD_CONFIDENCE
        )
    ]

    bird_confidence = max(
        (label["confidence"] for label in bird_labels),
        default=0.0,
    )

    return {
        "photo": str(photo_path),
        "bird_detected": bool(bird_labels),
        "bird_confidence": bird_confidence,
        "bird_labels": bird_labels,
        "all_labels": labels,
    }


def detect_burst(photo_paths):
    """
    Analyze every photograph in a burst.

    Returns an aggregate result.

    If any image fails, classification is marked incomplete.
    No photograph is deleted.
    """

    results = []
    errors = []

    for photo in photo_paths:

        try:
            result = detect_bird(photo)
            results.append(result)

            status = (
                "BIRD"
                if result["bird_detected"]
                else "NO BIRD"
            )

            print(
                f"{Path(photo).name}: "
                f"{status} "
                f"({result['bird_confidence']:.1%})",
                flush=True,
            )

        except MonthlyLimitReached as e:
            errors.append({
                "photo": str(photo),
                "error": str(e),
            })
            print(f"{photo}: LIMIT REACHED", flush=True)
            break

        except BirdDetectionError as e:
            errors.append({
                "photo": str(photo),
                "error": str(e),
            })
            print(f"{photo}: ERROR - {e}", flush=True)

    bird_photos = [
        r["photo"]
        for r in results
        if r["bird_detected"]
    ]

    # A burst is fully classified only when every image
    # was successfully analyzed.
    complete = (
        len(results) == len(photo_paths)
        and len(errors) == 0
    )

    if not complete:
        classification = "pending"
    elif bird_photos:
        classification = "bird"
    else:
        classification = "no_bird"

    return {
        "classification": classification,
        "complete": complete,
        "bird_detected": bool(bird_photos),
        "bird_photos": bird_photos,
        "photo_count": len(photo_paths),
        "analyzed_count": len(results),
        "results": results,
        "errors": errors,
    }


if __name__ == "__main__":

    if len(sys.argv) < 2:
        print(
            "Usage: python3 bird_detection.py "
            "/path/to/photo.jpg"
        )
        sys.exit(1)

    try:
        result = detect_bird(sys.argv[1])

        print(json.dumps(result, indent=2))

        print(
            "\nMonthly API usage:",
            catcam_stats.get_api_usage(),
            "/",
            catcam_stats.MONTHLY_API_LIMIT,
        )

    except BirdDetectionError as e:
        print(f"Detection failed: {e}")
        sys.exit(1)
