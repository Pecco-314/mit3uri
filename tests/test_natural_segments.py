import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/asr'))
from natural_segments import merge_reviewed_regions, plan_regions, sentence_spans
from audio_utils import speech_timestamps


class NaturalSegmentsTests(unittest.TestCase):
    def test_long_audio_offsets_and_joins_continuous_speech(self):
        vad = Mock()
        vad.get_speech_timestamps.side_effect = [
            [{'start': 1, 'end': 5}],
            [{'start': 0, 'end': 2}, {'start': 3, 'end': 5}],
            [{'start': 1, 'end': 2}],
        ]
        cleanup = Mock()
        result = speech_timestamps(vad, list(range(120)), sample_rate=10,
                                   batch_seconds=5, clear_cache=cleanup)
        self.assertEqual(result, [{'start': 1, 'end': 7}, {'start': 8, 'end': 10},
                                  {'start': 11, 'end': 12}])
        self.assertEqual([len(c.args[0]) for c in vad.get_speech_timestamps.call_args_list], [50, 50, 20])
        self.assertEqual(cleanup.call_count, 3)

    def test_pause_plan_preserves_all_audio_without_overlap(self):
        speech = [{'start': 4, 'end': 23}, {'start': 25, 'end': 44}, {'start': 47, 'end': 99}]
        songs = [{'id': 'song', 'start': 50, 'end': 80, 'language': 'Japanese'}]
        plan = plan_regions(120, speech, songs)
        self.assertEqual(plan[0]['start'], 0)
        self.assertEqual(plan[-1]['end'], 120)
        for a, b in zip(plan, plan[1:]):
            self.assertEqual(a['end'], b['start'])
        self.assertEqual(plan[0]['end'], 24)
        self.assertEqual([s for s in plan if s['kind'] == 'song'][0]['start'], 50)

    def test_vad_silence_is_retained_and_fallback_marked(self):
        plan = plan_regions(200, [], [])
        self.assertAlmostEqual(sum(s['end']-s['start'] for s in plan), 200)
        self.assertIn('duration_fallback', plan[0]['needsReview'])
        self.assertTrue(all('low_vad_activity' in s['needsReview'] for s in plan))

    def test_mixed_language_punctuation_survives_alignment(self):
        text = '你好！fan art tag。再见'
        words = ['你', '好', 'fan', 'art', 'tag', '再', '见']
        items = [{'text': w, 'start': i, 'end': i+0.8} for i, w in enumerate(words)]
        result = sentence_spans(text, items, 100, 7)
        self.assertEqual(''.join(s['text'] for s in result), text)
        self.assertEqual(result[1]['start'], 102)
        self.assertEqual(result[1]['end'], 104.8)

    def test_bad_alignment_is_not_presented_as_sentence_timestamps(self):
        for items in [[{'text': '错', 'start': 0, 'end': 1}],
                      [{'text': '你', 'start': -1, 'end': 1}],
                      [{'text': '你', 'start': 0, 'end': 10}]]:
            with self.subTest(items=items), self.assertRaises(ValueError):
                sentence_spans('你。', items, 100, 5)

    def test_invalid_song_ranges_rejected(self):
        with self.assertRaises(ValueError):
            plan_regions(100, [], [{'start': 20, 'end': 50}, {'start': 40, 'end': 60}])

    def test_semantic_merge_keeps_coverage_and_rejects_song_crossing(self):
        plan = plan_regions(200, [], [])
        merged = merge_reviewed_regions(plan, [{'ids': [plan[0]['id'], plan[1]['id']], 'reason': 'sentence continuation'}])
        self.assertEqual(merged[0]['start'], 0)
        self.assertEqual(merged[0]['end'], merged[1]['start'])
        plan[1]['kind'] = 'song'
        with self.assertRaises(ValueError):
            merge_reviewed_regions(plan, [{'ids': [plan[0]['id'], plan[1]['id']], 'reason': 'invalid'}])


if __name__ == '__main__':
    unittest.main()
