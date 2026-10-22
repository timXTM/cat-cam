"""Tests for the persistent CatCam species catalog."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import os

# catcam_stats initializes its database during import.
# Redirect that initialization to an isolated temporary directory.
_import_tempdir = tempfile.TemporaryDirectory()
os.environ["CATCAM_STATS_DB_PATH"] = str(
    Path(_import_tempdir.name) / "import_test.db"
)

import catcam_stats


class SpeciesCatalogTests(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

        self.db_path = Path(self.tempdir.name) / "species_test.db"

        # Redirect every catcam_stats database operation to this test DB.
        self.db_patch = patch.object(catcam_stats, "DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

        catcam_stats.initialize()
        catcam_stats.initialize_step4()

        self.bird_folder = str(Path(self.tempdir.name) / "bird")
        self.nonbird_folder = str(Path(self.tempdir.name) / "nonbird")

        with catcam_stats.connect() as conn:
            conn.execute("""
                INSERT INTO events
                (timestamp, trigger_source, folder, classification)
                VALUES (?, ?, ?, ?)
            """, ("2026-10-22T12:00:00+00:00",
                  "motion", self.bird_folder, "bird"))

            conn.execute("""
                INSERT INTO events
                (timestamp, trigger_source, folder, classification)
                VALUES (?, ?, ?, ?)
            """, ("2026-10-22T12:01:00+00:00",
                  "motion", self.nonbird_folder, "no_bird"))

    def test_builtin_species_available(self):
        options = catcam_stats.get_species_options()

        self.assertIn("Northern cardinal", options)

    def test_add_species_and_persistence(self):
        result = catcam_stats.add_species("Purple finch")

        self.assertTrue(result["added"])
        self.assertEqual(result["species"], "Purple finch")

        # A new database connection must still find the species.
        options = catcam_stats.get_species_options()

        self.assertIn("Purple finch", options)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT name FROM species_catalog
                WHERE name=?
            """, ("Purple finch",)).fetchone()

        self.assertEqual(row[0], "Purple finch")

    def test_duplicate_case_insensitive(self):
        first = catcam_stats.add_species("Purple finch")
        second = catcam_stats.add_species("purple FINCH")

        self.assertTrue(first["added"])
        self.assertFalse(second["added"])
        self.assertEqual(second["species"], "Purple finch")

        options = catcam_stats.get_species_options()

        matches = [
            name for name in options
            if name.casefold() == "purple finch"
        ]

        self.assertEqual(len(matches), 1)

    def test_confirm_added_species(self):
        catcam_stats.add_species("Purple finch")

        result = catcam_stats.set_confirmed_species(
            self.bird_folder, "Purple finch"
        )

        self.assertEqual(result["confirmed_species"], "Purple finch")
        self.assertEqual(result["species_status"], "confirmed")

        with catcam_stats.connect() as conn:
            row = conn.execute("""
                SELECT confirmed_species, species_status
                FROM events WHERE folder=?
            """, (self.bird_folder,)).fetchone()

        self.assertEqual(row, ("Purple finch", "confirmed"))

    def test_unknown_species_rejected(self):
        with self.assertRaises(ValueError):
            catcam_stats.set_confirmed_species(
                self.bird_folder, "Imaginary purple bird"
            )

    def test_clear_confirmation(self):
        catcam_stats.add_species("Purple finch")
        catcam_stats.set_confirmed_species(
            self.bird_folder, "Purple finch"
        )

        result = catcam_stats.set_confirmed_species(
            self.bird_folder, None
        )

        self.assertIsNone(result["confirmed_species"])
        self.assertEqual(result["species_status"], "unreviewed")

    def test_nonbird_confirmation_rejected(self):
        catcam_stats.add_species("Purple finch")

        with self.assertRaises(ValueError):
            catcam_stats.set_confirmed_species(
                self.nonbird_folder, "Purple finch"
            )

    def test_invalid_species_names(self):
        for name in ("", " ", "A" * 101, 'Bird\nName', None):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    catcam_stats.add_species(name)


if __name__ == "__main__":
    unittest.main()
