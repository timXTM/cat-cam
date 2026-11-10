"""Gallery pagination and historical-folder regression tests."""
import sqlite3
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_import_tempdir = tempfile.TemporaryDirectory()
os.environ['CATCAM_STATS_DB_PATH'] = str(Path(_import_tempdir.name) / 'import_test.db')
import catcam_gallery


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / 'wildlife'
        self.base.mkdir()
        self.db = Path(self.tmp.name) / 'events.db'
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, folder TEXT, '
                         'classification TEXT, deleted INTEGER, photo_count INTEGER)')
        self.patches = [
            patch.object(catcam_gallery, 'BASE_DIR', self.base),
            patch.object(catcam_gallery.catcam_stats, 'DB_PATH', self.db),
            patch.object(catcam_gallery.catcam_advanced, 'get', return_value='America/New_York'),
            patch.object(catcam_gallery.catcam_activity, 'get_activity', side_effect=self.activity),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        with catcam_gallery._legacy_lock:
            catcam_gallery._legacy_snapshot = None
            catcam_gallery._legacy_base_dir = None
            catcam_gallery._legacy_refreshed_at = 0

    def folder(self, name, count=6, classification=None, deleted=False, recorded_count=None):
        folder = self.base / '2026-10-30' / name
        folder.mkdir(parents=True)
        for n in range(1, count + 1):
            (folder / f'{n:02d}.jpg').touch()
        if classification is not None:
            with sqlite3.connect(self.db) as conn:
                conn.execute('INSERT INTO events (folder, classification, deleted, photo_count) '
                             'VALUES (?, ?, ?, ?)',
                             (str(folder), classification, int(deleted),
                              count if recorded_count is None else recorded_count))
        return folder

    def activity(self, **filters):
        with sqlite3.connect(self.db) as conn:
            birds = conn.execute("SELECT folder FROM events WHERE classification='bird'").fetchall()
        events = [{'folder': folder, 'bird_type': 'Cardinal',
                   'detection_engine': 'local_ai'} for (folder,) in birds]
        if filters.get('bird_type') and filters['bird_type'] != 'Cardinal':
            events = []
        return {'events': events, 'available_bird_types': ['Cardinal']}

    def test_bird_page_does_not_scan_archive(self):
        self.folder('06-00-00', classification='bird')
        self.folder('07-00-00', classification='no_bird')
        with patch.object(catcam_gallery, '_scan_archive', side_effect=AssertionError('full scan')):
            result = catcam_gallery.gallery(mode='bird')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['events'][0]['event'], '06-00-00')
        self.assertEqual(len(result['events'][0]['photos']), 6)

    def test_all_keeps_legacy_and_skips_deleted(self):
        self.folder('06-00-00', classification='bird')
        self.folder('07-00-00', classification='no_bird', deleted=True)
        self.folder('08-00-00', count=2)  # No database row
        self.folder('09-00-00', count=0)  # Empty historical folder
        with patch.object(catcam_gallery, '_scan_archive', wraps=catcam_gallery._scan_archive) as scan:
            first = catcam_gallery.gallery(mode='all', page_size=1)
            second = catcam_gallery.gallery(mode='all', page=2, page_size=1)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(first['total'], 2)
        self.assertEqual(first['events'][0]['event'], '08-00-00')
        self.assertEqual(second['events'][0]['event'], '06-00-00')
        self.assertEqual(len(first['events'][0]['photos']), 2)

    def test_filters_and_sort(self):
        self.folder('06-00-00', classification='bird')
        self.folder('07-00-00', classification='no_bird')
        self.folder('08-00-00', classification='bird')
        with patch.object(catcam_gallery, '_scan_archive', side_effect=AssertionError('full scan')):
            result = catcam_gallery.gallery(mode='no_bird')
            birds = catcam_gallery.gallery(mode='bird', bird_type='Cardinal',
                                           start_hour='6', end_hour='7')
            oldest = catcam_gallery.gallery(mode='bird', order='oldest')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['events'][0]['event'], '07-00-00')
        self.assertEqual([e['event'] for e in birds['events']], ['06-00-00'])
        self.assertEqual([e['event'] for e in oldest['events']], ['06-00-00', '08-00-00'])

    def test_new_database_burst_visible_without_refresh(self):
        self.folder('06-00-00', classification='bird')
        catcam_gallery.gallery(mode='all')  # Build historical index.
        self.folder('08-00-00', classification='bird')
        result = catcam_gallery.gallery(mode='all')
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['events'][0]['event'], '08-00-00')

    def test_older_database_row_with_zero_count_still_has_photos(self):
        self.folder('06-00-00', count=2, classification='bird', recorded_count=0)
        with patch.object(catcam_gallery, '_scan_archive', side_effect=AssertionError('full scan')):
            result = catcam_gallery.gallery(mode='bird')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['events'][0]['photos'], ['01.jpg', '02.jpg'])


if __name__ == '__main__':
    unittest.main()
