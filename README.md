# CatCam — Bird Activity Stage 1

## Metric

**Bird-positive capture events** = number of capture bursts whose event classification is `bird`. Each burst is counted **once**, regardless of how many photographs show a bird or how many Google Vision labels are returned. Repeated motion triggers may create multiple events; the metric is not a count of individual birds or distinct bird visits.

## Install

1. Copy `catcam_activity.py` to `/home/pi/catcam/catcam_activity.py` (new file).
2. Replace `wildlife_camera.py` with the supplied `wildlife_camera_activity.py`, renamed to `wildlife_camera.py`.
3. Optionally copy `test_catcam_activity.py` for offline testing.
4. Commit/push in GitHub Desktop; pull on Pi.
5. Run `python3 -m py_compile catcam_activity.py wildlife_camera.py` and `python3 -m unittest -v test_catcam_activity.py`.
6. Restart CatCam only after checking for local changes and a successful compilation.

## Read-only API

`GET /api/bird-activity`

Optional filters:

- `start=YYYY-MM-DD` — local start date, inclusive
- `end=YYYY-MM-DD` — local end date, inclusive
- `start_hour=0..23` and `end_hour=0..23` — local hours, inclusive; overnight ranges supported
- `bird_type=Northern%20cardinal` — a single normalized bird type; `Unknown bird type` is valid

All date/time calculations use `America/New_York` (local DST handled automatically). The output includes `total_events`, `by_hour` (24 entries including zero hours), `by_day`, `by_bird_type`, `available_bird_types`, and `events` (matching event IDs and folders for Stage 3 Gallery integration).

Sample test:

```bash
curl -s 'http://localhost:8080/api/bird-activity' | python3 -m json.tool | head -70
curl -s 'http://localhost:8080/api/bird-activity?start=2026-10-18&end=2026-10-19&start_hour=15&end_hour=19' | python3 -m json.tool | head -70
```

## Hierarchical bird-type identification (revised)

The basic metric remains **one bird-positive capture event**, never one bird or one photo. The analytics read the Google Vision labels saved in `photo_detections` for the first bird-positive photo; no API requests or database changes are needed.

- CatCam prefers a specific recognized species (e.g. `Northern cardinal`) if confidence is at least **65%** and it leads another species candidate by at least **10 percentage points**.
- If no specific species meets that standard, a recognized broader bird label (e.g. `Cardinal`, `Finch`, `Sparrow`, `Woodpecker`) at **65%** or higher is retained instead of incorrectly labeling the event Unknown.
- If two close species candidates belong to the same broader type (e.g. Downy and Hairy woodpecker), CatCam can select that common broader type.
- `Bird` alone becomes `Unknown bird type`. These are heuristics, not definitive biological identification.
- **Hierarchical filters:** `bird_type=Cardinal` includes events assigned `Cardinal` **or** `Northern cardinal`; `bird_type=Northern%20cardinal` includes only Northern cardinal. Likewise `Finch` includes House finch and American goldfinch, and so forth. `by_bird_type` still counts each event **only once** under its assigned (most specific reliable) type.
- `available_bird_types` includes assigned types plus their filterable parent categories. Parent groups are practical bird-type labels and are not a claim of exact taxonomic classification.

The known-species and broader-label vocabularies are maintained explicitly in `catcam_activity.py` (`SPECIES_ALIASES`, `BROAD_ALIASES`, and `TYPE_PARENTS`). New bird types can be added as they appear in actual data. The classifier never invents a species label that Google Vision did not support.

### Updating an existing Stage 1 installation

Replace **only** `catcam_activity.py` with the revised version. Optionally replace `test_catcam_activity.py` and update this documentation. The existing Stage 1 `wildlife_camera.py` API integration **does not change**. This avoids replacing camera, Discord, or Gallery code unnecessarily.

Run `python3 -m unittest -v test_catcam_activity.py`, then `sudo systemctl restart catcam.service` after the new file has been pulled onto the Pi. No migration or new Vision requests are needed.

## Performance

Stage 1 reads the existing SQLite `events` and `photo_detections` tables; it does not alter or backfill historical rows. It returns matching event metadata for later Gallery filtering. For very large histories, the next iteration should paginate `events` and add database indexes / SQL-level date filtering to reduce Pi Zero CPU and response sizes.


---

## Shared Navigation and Camera Health (October 2026)

### Shared navigation

CatCam uses a shared header across Dashboard, Settings, Gallery,
Bird Activity, photo detail pages, and the legacy Bird Gallery.

The shared header consists of:

- `catcam_header.css`: Common header styling and layout.
- `catcam_header.js`: Navigation and camera-status behavior.

All pages use consistent header spacing, navigation, and status indicators.

### Camera health monitoring

The shared header displays three camera states:

- **Live:** The camera is actively capturing frames.
- **Offline:** The camera has stopped producing frames.
- **Checking:** The initial camera-health request is in progress.

All pages retrieve camera health from the `/api/status` endpoint.

The endpoint includes a `camera_live` boolean indicating whether
the camera has successfully captured a frame within the last 90 seconds.

Camera-health monitoring uses existing camera activity rather than
opening additional video streams, minimizing Raspberry Pi CPU usage.

### Troubleshooting

To check camera health from the Raspberry Pi:

    curl -s http://192.168.1.201:8080/api/status

Look for `"camera_live": true` in the response.

The CatCam web server currently binds to its LAN address.
Requests to `localhost:8080` may therefore fail.

To restart CatCam:

    sudo systemctl restart catcam.service

To inspect its status:

    sudo systemctl status catcam.service --no-pager
