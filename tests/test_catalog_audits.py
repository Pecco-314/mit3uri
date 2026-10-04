"""Keep curated evidence bound to the correct recording and broadcast."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from catalog_audits import apply_audits


class CatalogAuditTests(unittest.TestCase):
    def setUp(self):
        self.raw = {'sessions': [{'session_id': 'old', 'live_date': '2025-01-01', 'included_in_total': 1},
                                {'session_id': 'target', 'live_date': '2025-01-01', 'included_in_total': 1}],
                    'recordings': [{'session_id': 'old', 'bvid': 'tail'}, {'session_id': 'target', 'bvid': 'official'}],
                    'evidence': []}
        self.audit = {'roomId': 1, 'merges': [{'fromSession': 'old', 'toSession': 'target',
                      'date': '2025-01-01', 'bvid': 'tail', 'targetAnchorBvid': 'official'}]}

    def test_tail_moves_without_changing_source_snapshot(self):
        before = copy.deepcopy(self.raw)
        result = apply_audits(self.raw, self.audit)
        self.assertEqual(before, self.raw)
        self.assertEqual(result['sessionAliases'], {'old': 'target'})
        self.assertFalse(result['sessions'][0]['included_in_total'])
        self.assertEqual({r['session_id'] for r in result['recordings']}, {'target'})

    def test_id_reuse_cannot_apply_evidence_to_another_video(self):
        self.raw['recordings'][1]['bvid'] = 'another'
        with self.assertRaisesRegex(ValueError, 'assignment changed'):
            apply_audits(self.raw, self.audit)

    def test_new_independent_evidence_prevents_retiring_a_session(self):
        self.raw['evidence'] = [{'session_id': 'old', 'excluded_short': 0}]
        with self.assertRaisesRegex(ValueError, 'independent evidence'):
            apply_audits(self.raw, self.audit)

    def test_unreviewed_sources_cannot_be_discarded(self):
        self.raw['recordings'].append({'session_id': 'old', 'bvid': 'new-source'})
        with self.assertRaisesRegex(ValueError, 'remaining recordings'):
            apply_audits(self.raw, self.audit)

    def test_clock_conflict_is_rejected(self):
        item = {'date': '2025-01-01', 'anchorBvid': 'official', 'startedAt': '2025-01-01T20:00:00+08:00',
                'precision': 'minute', 'timeEvidence': 'verified_replay_clock',
                'evidence': {'frames': [{'offsetSeconds': 660, 'clock': '20:11:30'},
                                        {'offsetSeconds': 780, 'clock': '20:13:30'}]}}
        audits = {'starts': {'target': item}}
        self.assertIn('target', apply_audits(self.raw, audits)['auditedStarts'])
        item['evidence']['frames'][1]['clock'] = '20:14:30'
        with self.assertRaisesRegex(ValueError, 'Conflicting clock'):
            apply_audits(self.raw, audits)

    def test_published_parts_do_not_cross_sessions(self):
        catalog = json.loads((ROOT / 'site/data/catalog.json').read_text())
        matches = [(r['id'], s) for r in catalog['sessions'] for s in r['sources'] if s['id'] == 'BV1kYCVBJEBn']
        self.assertEqual({sid: s['recordingPages'] for sid, s in matches},
                         {'MIT3URI-0344': [1], 'MIT3URI-0345': [2, 3, 4]})
        self.assertEqual({sid: s['url'].split('?')[-1] for sid, s in matches},
                         {'MIT3URI-0344': 'p=1', 'MIT3URI-0345': 'p=2'})
        self.assertNotIn('MIT3URI-0347', {r['id'] for r in catalog['sessions']})

    def test_trusted_part_times_preserve_aligned_seconds(self):
        audit = json.loads((ROOT / 'content/time-audits.json').read_text())
        catalog = {r['id']: r for r in json.loads((ROOT / 'site/data/catalog.json').read_text())['sessions']}
        expected = {'0014': '19:58:41', '0039': '20:58:05', '0057': '20:58:13', '0059': '12:03:51',
                    '0089': '11:05:26', '0093': '00:10:09', '0119': '13:58:15', '0224': '21:00:16',
                    '0275': '00:15:23'}
        for suffix, clock in expected.items():
            sid = 'MIT3URI-' + suffix
            self.assertEqual(catalog[sid]['startedAt'][11:19], clock)
            self.assertEqual(catalog[sid]['timeEvidence'], 'aligned_recording_part')
            self.assertEqual(catalog[sid]['startedAtPrecision'], 'second')
            self.assertIsNone(catalog[sid]['liveDurationSeconds'])
            self.assertIn('audioMatches', audit['starts'][sid]['evidence'])

    def test_inconsistent_part_alignment_is_rejected(self):
        audit = json.loads((ROOT / 'content/time-audits.json').read_text())
        item = copy.deepcopy(audit['starts']['MIT3URI-0039'])
        item['anchorBvid'] = 'official'
        item['evidence']['recordingBvid'] = 'tail'
        for row in self.raw['sessions']:
            row['live_date'] = item['date']
        self.raw['recordings'][0].update(session_id='target', source_mid=item['evidence']['uploaderId'])
        self.assertIn('target', apply_audits(self.raw, {'starts': {'target': item}})['auditedStarts'])
        item['evidence']['audioMatches'][1]['officialOffset'] += 60
        with self.assertRaisesRegex(ValueError, 'Conflicting audio alignment'):
            apply_audits(self.raw, {'starts': {'target': item}})


if __name__ == '__main__':
    unittest.main()
