"""Run on Mac/Pi: python3 -m unittest test_catcam_activity.py"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from catcam_activity import get_activity, identify_bird_type, matches_bird_type, _labels, UNKNOWN


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'stats.db'
        with sqlite3.connect(self.db) as conn:
            conn.executescript('''
                CREATE TABLE events (id INTEGER PRIMARY KEY, timestamp TEXT, folder TEXT,
                                     trigger_source TEXT, classification TEXT,
                                     first_bird_photo INTEGER, bird_labels_json TEXT,
                                     detection_engine TEXT,
                                     ai_species TEXT,
                                     ai_species_score REAL,
                                     confirmed_species TEXT,
                                     species_status TEXT);
                CREATE TABLE photo_detections (event_id INTEGER, photo_path TEXT,
                                               bird_detected INTEGER, labels_json TEXT);
            ''')
            entries = [
                (1, '2026-10-18T21:45:00+00:00', '/photos/1', 'motion', 'bird', 1, '[]'),
                (2, '2026-10-18T22:15:00+00:00', '/photos/2', 'motion', 'bird', 2, '[]'),
                (3, '2026-10-19T03:00:00+00:00', '/photos/3', 'manual', 'no_bird', None, '[]'),
                (4, '2026-10-19T12:00:00+00:00', '/photos/4', 'motion', 'bird', 1, '[]'),
            ]
            conn.executemany('''INSERT INTO events
                (id, timestamp, folder, trigger_source, classification,
                 first_bird_photo, bird_labels_json)
                VALUES (?,?,?,?,?,?,?)''', entries)
            conn.executemany('INSERT INTO photo_detections VALUES (?,?,?,?)', [
                (1, '01.jpg', 1, json.dumps([{'name':'Bird','confidence':.96}, {'name':'Northern cardinal','confidence':.81}])),
                (2, '02.jpg', 1, json.dumps([{'name':'House finch','confidence':.83}])),
                (4, '01.jpg', 1, json.dumps([{'name':'Cardinal','confidence':.99}])),
            ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_are_events_not_photos(self):
        data = get_activity(db_path=self.db)
        self.assertEqual(data['total_events'], 3)
        self.assertEqual(data['by_hour'][17]['events'], 1)
        self.assertEqual(data['by_hour'][18]['events'], 1)
        self.assertEqual(data['by_hour'][8]['events'], 1)
        self.assertEqual(sum(x['events'] for x in data['by_bird_type']), 3)

    def test_filters(self):
        data = get_activity(start='2026-10-18', end='2026-10-18',
                            start_hour='17', end_hour='17', bird_type='Northern cardinal', db_path=self.db)
        self.assertEqual(data['total_events'], 1)
        self.assertEqual(data['events'][0]['id'], 1)

    def test_unknown(self):
        self.assertEqual(identify_bird_type(_labels('[{"name":"Cardinal","confidence":0.99}]'))[0], 'Cardinal')
        self.assertEqual(identify_bird_type(_labels('[{"name":"House finch","confidence":0.8}, {"name":"Northern cardinal","confidence":0.75}]'))[0], UNKNOWN)

    def test_broad_category_and_hierarchy(self):
        data = get_activity(db_path=self.db)
        self.assertEqual(dict((x['bird_type'], x['events']) for x in data['by_bird_type']),
                         {'Northern cardinal': 1, 'House finch': 1, 'Cardinal': 1})
        self.assertEqual(get_activity(bird_type='Cardinal', db_path=self.db)['total_events'], 2)
        self.assertEqual(get_activity(bird_type='Northern cardinal', db_path=self.db)['total_events'], 1)
        self.assertEqual(get_activity(bird_type='Finch', db_path=self.db)['total_events'], 1)
        self.assertIn('Cardinal', data['available_bird_types'])
        self.assertIn('Finch', data['available_bird_types'])

    def test_broad_fallback_and_species_priority(self):
        self.assertEqual(identify_bird_type(_labels('[{"name":"Bird","confidence":0.99}, {"name":"Finch","confidence":0.80}]'))[0], 'Finch')
        self.assertEqual(identify_bird_type(_labels('[{"name":"Cardinal","confidence":0.9}, {"name":"Northern cardinal","confidence":0.72}]'))[0], 'Northern cardinal')
        self.assertEqual(identify_bird_type(_labels('[{"name":"Bird","confidence":0.99}]'))[0], UNKNOWN)
        self.assertEqual(identify_bird_type(_labels('[{"name":"Downy woodpecker","confidence":0.8}, {"name":"Hairy woodpecker","confidence":0.77}]'))[0], 'Woodpecker')

    def test_bad_filter(self):
        with self.assertRaises(ValueError):
            get_activity(start_hour='3', db_path=self.db)


    def test_ai_estimate_and_manual_confirmation(self):
        import sqlite3

        with sqlite3.connect(self.db) as conn:
            conn.execute("""
                UPDATE events
                SET detection_engine='local_ai',
                    ai_species='Cardinalis cardinalis',
                    ai_species_score=0.91,
                    confirmed_species='House finch',
                    species_status='confirmed'
                WHERE id=1
            """)

        data = get_activity(db_path=self.db)
        event = next(e for e in data['events'] if e['id'] == 1)

        self.assertEqual(event['bird_type'], 'House finch')
        self.assertEqual(event['estimated_species'], 'Northern cardinal')
        self.assertEqual(event['confirmed_species_display'], 'House finch')
        self.assertEqual(event['identification_status'], 'confirmed')
        self.assertAlmostEqual(event['estimated_confidence'], 0.91)

    def test_identification_status_filters(self):
        import sqlite3

        with sqlite3.connect(self.db) as conn:
            conn.execute("""
                UPDATE events
                SET detection_engine='local_ai',
                    ai_species='Cardinalis cardinalis',
                    ai_species_score=0.91,
                    confirmed_species='House finch',
                    species_status='confirmed'
                WHERE id=1
            """)

            # Make event 4 a bird-positive burst without species identification.
            conn.execute("""
                UPDATE photo_detections
                SET labels_json='[]'
                WHERE event_id=4
            """)

        all_events = get_activity(db_path=self.db)

        self.assertEqual(all_events['total_events'], 3)
        self.assertEqual(
            all_events['identification_counts'],
            {'confirmed': 1, 'estimated': 1, 'unidentified': 1}
        )

        expected = {
            'confirmed': 1,
            'estimated': 2,
            'unidentified': 4,
        }

        for status, event_id in expected.items():
            with self.subTest(status=status):
                result = get_activity(
                    identification_status=status,
                    db_path=self.db
                )

                self.assertEqual(result['total_events'], 1)
                self.assertEqual(result['events'][0]['id'], event_id)
                self.assertEqual(
                    result['events'][0]['identification_status'],
                    status
                )
                self.assertEqual(
                    result['identification_counts'][status], 1
                )

    def test_invalid_identification_status(self):
        with self.assertRaises(ValueError):
            get_activity(
                identification_status='invalid',
                db_path=self.db
            )


if __name__ == '__main__':
    unittest.main()
