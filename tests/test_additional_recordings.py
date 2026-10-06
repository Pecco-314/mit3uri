"""Protect reviewed session scope and per-session coverage of multi-part uploads."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from additional_recordings import merge_additional_recordings, fetch_collection
from export_data import build_catalog
from merge_supplement import timestamp


class AdditionalRecordingsTest(unittest.TestCase):
    def setUp(self):
        self.raw = {'exportedAt': '2026-10-03', 'markers': [], 'evidence': [], 'recordings': [],
                    'sessions': [{'session_id': 'MIT3URI-0001', 'included_in_total': 1,
                                  'title': '歌回', 'live_date': '2026-07-11',
                                  'start_time_precision': 'date', 'start_timestamp': None,
                                  'preferred_bvid_mode': 'single', 'catalog_generated_at': '2026-10-03'}]}
        self.config = {'source': {'mid': 3493077901642666, 'name': '最后--年', 'priority': 7,
                                  'url': 'https://space.bilibili.com/3493077901642666'},
                       'excludedVideos': {}, 'recordings': [
                           {'bvid': 'BV1234567890', 'sessionId': 'MIT3URI-0001', 'title': '歌回',
                            'durationSeconds': 13000, 'recordingPages': [1],
                            'pages': [{'page': 1, 'part': '三理视角', 'duration': 6000},
                                      {'page': 2, 'part': '其他视角', 'duration': 7000}]}]}

    def test_other_view_is_not_added_to_session_length_or_start(self):
        raw, added = merge_additional_recordings(self.raw, self.config)
        session = build_catalog(raw)['sessions'][0]
        self.assertEqual(len(added), 1)
        self.assertEqual(session['recordingDurationSeconds'], 6000)
        self.assertEqual(session['sources'][0]['durationSeconds'], 13000)
        self.assertIsNone(session['startedAt'])
        self.assertEqual(self.raw['recordings'], [])

    def test_reviewed_recording_from_another_uploader_keeps_its_identity(self):
        entry = self.config['recordings'][0]
        entry['source'] = {'mid': 1702090167, 'name': '青李柠檬青橘碳酸水',
                           'priority': 4, 'url': 'https://space.bilibili.com/1702090167'}
        raw, _ = merge_additional_recordings(self.raw, self.config)
        self.assertEqual(raw['recordings'][0]['source_mid'], 1702090167)
        self.assertEqual(raw['recordings'][0]['source_priority'], 4)
        with self.assertRaisesRegex(ValueError, 'owner'):
            merge_additional_recordings(self.raw, self.config,
                                       {'BV1234567890': dict(entry, ownerId=999)})

    def test_refresh_is_idempotent_and_cannot_create_a_session(self):
        raw, _ = merge_additional_recordings(self.raw, self.config)
        again, added = merge_additional_recordings(raw, self.config)
        self.assertEqual(again, raw)
        self.assertEqual(added, [])
        self.config['recordings'][0]['sessionId'] = 'MIT3URI-missing'
        with self.assertRaises(ValueError):
            merge_additional_recordings(self.raw, self.config)

    def test_external_activity_cannot_be_enabled_in_reviewed_list(self):
        self.config['excludedVideos']['BV1234567890'] = '外部活动'
        with self.assertRaises(ValueError):
            merge_additional_recordings(self.raw, self.config)

    def test_changed_part_order_requires_review(self):
        changed = copy.deepcopy(self.config['recordings'][0])
        changed['pages'][0]['part'] = '其他视角'
        with self.assertRaises(ValueError):
            merge_additional_recordings(self.raw, self.config, {'BV1234567890': changed})

    def test_collection_reads_second_page_and_rejects_missing_page(self):
        self.config['source']['seasonId'] = 8292682
        pages = []
        for ids in (['BV0000000001', 'BV0000000002'], ['BV0000000003']):
            pages.append({'meta': {'mid': self.config['source']['mid'], 'season_id': 8292682},
                          'page': {'total': 3}, 'archives': [{'bvid': b} for b in ids]})
        calls = []
        def fetch(url):
            calls.append(url)
            return pages[len(calls)-1]
        result = fetch_collection(self.config, fetch)
        self.assertEqual(result['bvids'], ['BV0000000001', 'BV0000000002', 'BV0000000003'])
        self.assertIn('page_num=2', calls[1])
        calls.clear()
        pages[1]['archives'] = []
        with self.assertRaises(ValueError):
            fetch_collection(self.config, fetch)

    def test_new_collection_upload_matches_existing_broadcast_without_whitelist(self):
        self.config['recordings'] = []
        start = timestamp('2026-07-11T20:00:00+08:00')
        self.raw['sessions'][0].update(start_timestamp=start, start_time_precision='second')
        self.raw['markers'] = [{'cmd': 'LIVE', 'timestamp': start}, {'cmd': 'PREPARING', 'timestamp': start+6000}]
        self.raw['evidence'] = [{'session_id': 'MIT3URI-0001', 'source': 'database',
                                'start_timestamp': start, 'end_timestamp': start+6000, 'excluded_short': 0}]
        video = {'title': '【三理Mit3uri录播】歌回 2026.07.11', 'durationSeconds': 5980,
                 'ownerId': self.config['source']['mid'],
                 'pages': [{'page': 1, 'part': '07.11 20:00:20', 'duration': 5980}]}
        snapshot = {'collection': {'total': 1, 'bvids': ['BV1234567890']}, 'videos': {'BV1234567890': video}}
        raw, added = merge_additional_recordings(self.raw, self.config, snapshot)
        self.assertEqual(added, [{'bvid': 'BV1234567890', 'session': 'MIT3URI-0001'}])
        self.assertEqual(len(raw['sessions']), 1)
        video['pages'][0]['part'] = '其他主播视角'
        with self.assertRaises(ValueError):
            merge_additional_recordings(self.raw, self.config, snapshot)

    def test_incomplete_collection_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            merge_additional_recordings(self.raw, self.config, {
                'collection': {'total': 2, 'bvids': ['BV1234567890']}, 'videos': {}})
