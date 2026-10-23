"""Integration tests for manual bird identification and photo cleanup."""

import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# Isolate the database before importing CatCam modules.
_import_dir = tempfile.TemporaryDirectory()
os.environ["CATCAM_STATS_DB_PATH"] = str(
    Path(_import_dir.name) / "import_test.db"
)

import catcam_stats

# Avoid importing Pillow-dependent thumbnail code on the Mac.
fake_thumbnails = types.ModuleType("catcam_thumbnails")
fake_thumbnails.delete_event_thumbnails = lambda folder: 0

with patch.dict(sys.modules, {"catcam_thumbnails": fake_thumbnails}):
    import catcam_cleanup


class CleanupOverrideTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        root = Path(self.temp.name)
        self.db = root / "test.db"
        self.base = root / "wildlife"

        db_patch = patch.object(catcam_stats, "DB_PATH", self.db)
        db_patch.start()
        self.addCleanup(db_patch.stop)

        base_patch = patch.object(catcam_cleanup, "BASE_DIR", self.base)
        base_patch.start()
        self.addCleanup(base_patch.stop)

        settings_patch = patch.object(
            catcam_cleanup.catcam_advanced,
            "get",
            side_effect=lambda key: 24 if key == "retention_hours" else None
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

        catcam_stats.initialize()
        catcam_stats.initialize_step4()

    def make_event(self, event_time, classification="no_bird"):
        folder = self.base / "2026-10-20" / event_time
        folder.mkdir(parents=True)

        photos = []
        for number in range(1, 7):
            photo = folder / f"{number:02d}.jpg"
            photo.write_bytes(b"temporary test photograph")
            photos.append(photo)

        timestamp = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        ).isoformat()

        with catcam_stats.connect() as conn:
            cursor = conn.execute(
                """INSERT INTO events
                   (timestamp, trigger_source, folder, classification,
                    photo_count, bird_photo_count)
                   VALUES (?, 'motion', ?, ?, 6, 0)""",
                (timestamp, str(folder), classification)
            )
            event_id = cursor.lastrowid

            for photo in photos:
                conn.execute(
                    """INSERT INTO photo_detections
                       (event_id, photo_path, bird_detected, confidence)
                       VALUES (?, ?, 0, 0)""",
                    (event_id, str(photo))
                )

        return event_id, folder, photos

    def test_manual_bird_survives_cleanup(self):
        event_id, folder, photos = self.make_event("10-00-00")

        result = catcam_stats.set_confirmed_species(
            folder, "Northern cardinal"
        )

        self.assertEqual(result["classification"], "bird")
        self.assertEqual(
            result["original_ai_classification"], "no_bird"
        )

        removed = catcam_cleanup.cleanup_once()

        self.assertEqual(removed, 0)
        self.assertTrue(all(photo.exists() for photo in photos))

        with catcam_stats.connect() as conn:
            row = conn.execute(
                "SELECT classification, deleted FROM events WHERE id=?",
                (event_id,)
            ).fetchone()

        self.assertEqual(row, ("bird", 0))

    def test_unconfirmed_nonbird_is_deleted(self):
        event_id, folder, photos = self.make_event("11-00-00")

        removed = catcam_cleanup.cleanup_once()

        self.assertEqual(removed, 1)
        self.assertFalse(folder.exists())
        self.assertTrue(all(not photo.exists() for photo in photos))

        with catcam_stats.connect() as conn:
            deleted = conn.execute(
                "SELECT deleted FROM events WHERE id=?",
                (event_id,)
            ).fetchone()[0]

        self.assertEqual(deleted, 1)

    def test_stale_cleanup_list_cannot_delete_confirmed_bird(self):
        event_id, folder, photos = self.make_event("12-00-00")

        # Simulate cleanup discovering the event before manual review.
        stale_candidates = catcam_cleanup.eligible_events()
        self.assertEqual(len(stale_candidates), 1)

        # User identifies the bird after cleanup has built its list.
        catcam_stats.set_confirmed_species(
            folder, "Northern cardinal"
        )

        # Force cleanup to process its outdated list.
        with patch.object(
            catcam_cleanup,
            "eligible_events",
            return_value=stale_candidates
        ):
            removed = catcam_cleanup.cleanup_once()

        self.assertEqual(removed, 0)
        self.assertTrue(all(photo.exists() for photo in photos))

        with catcam_stats.connect() as conn:
            row = conn.execute(
                "SELECT classification, deleted FROM events WHERE id=?",
                (event_id,)
            ).fetchone()

        self.assertEqual(row, ("bird", 0))


if __name__ == "__main__":
    unittest.main()
