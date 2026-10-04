"""Check that refreshes preserve identities and keep ambiguous same-day streams apart."""
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from merge_supplement import merge_supplement, timestamp


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.raw = {'sessions': [{'session_id': 'MIT3URI-0001', 'title': '歌回', 'live_date': '2026-08-05',
                                 'start_time_precision': 'second', 'start_timestamp': timestamp('2026-08-05T12:00:00+08:00'),
                                 'duration_seconds': 7200}], 'evidence': [], 'recordings': []}
        self.supplement = {'fetchedAt': '2026-10-03T12:00:00+08:00', 'history': [],
                           'recordings': [], 'excludedBvids': [], 'vtbStarts': [], 'overrides': {}}

    def test_existing_identity_survives_history_refresh(self):
        self.supplement['history'] = [{'month': '2026-08', 'sessions': [
            {'start_time': '2026-08-05 12:00:00', 'end_time': '2026-08-05 14:00:00', 'title': '歌回'}]}]
        merged, report = merge_supplement(self.raw, self.supplement)
        self.assertEqual(len(merged['sessions']), 1)
        self.assertEqual(merged['sessions'][0]['session_id'], 'MIT3URI-0001')
        self.assertEqual(report['newSessions'], [])

    def test_later_stream_on_catalog_boundary_day_is_added(self):
        self.supplement['history'] = [{'month': '2026-08', 'sessions': [
            {'start_time': '2026-08-05 20:00:00', 'end_time': '2026-08-05 22:00:00', 'title': '歌回'}]}]
        merged, report = merge_supplement(self.raw, self.supplement)
        self.assertEqual(len(merged['sessions']), 2)
        self.assertEqual(len(report['newSessions']), 1)

    def test_same_title_and_duration_do_not_resolve_two_streams(self):
        second = dict(self.raw['sessions'][0], session_id='MIT3URI-0002', start_timestamp=timestamp('2026-08-05T20:00:00+08:00'))
        self.raw['sessions'].append(second)
        self.supplement['recordings'] = [{'bvid': 'BV1234567890', 'title': '歌回 2026-08-05',
                                         'duration_seconds': 7200, 'parsed_day': '2026-08-05',
                                         'parsed_start': None, 'parsed_precision': 'date', 'display_title': '歌回'}]
        merged, report = merge_supplement(self.raw, self.supplement)
        self.assertEqual(merged['recordings'], [])
        self.assertEqual(len(report['unresolvedRecordings']), 1)

    def test_failed_month_stops_refresh_without_mutation(self):
        before = copy.deepcopy(self.raw)
        self.supplement['history'] = [{'month': '2026-09', 'error': 'network unavailable'}]
        with self.assertRaises(ValueError):
            merge_supplement(self.raw, self.supplement)
        self.assertEqual(self.raw, before)
