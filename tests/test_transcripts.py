import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/asr'))
from export_transcripts import parse_transcript
from audio_utils import review_flags


class TranscriptTests(unittest.TestCase):
    def test_hotword_echo_is_flagged_without_rewriting_the_text(self):
        words = ['三理', 'Mit3uri', '三三', '三理理', '理电池']
        self.assertIn('suspected_hotword_echo', review_flags('Mit3uri, 三理, 三三, 三理理, 理电池。', words, 24, 1024))
        self.assertEqual(review_flags('大家可以叫我三理理。', words, 12, 1024), [])
        self.assertIn('token_limit', review_flags('Oh, oh', [], 1024, 1024))

    def document(self, body, **overrides):
        meta = {'schemaVersion': 1, 'sessionId': 's1', 'status': 'draft', 'timing': 'chunk', 'source': {'bvid': 'BV1eiXRYHEsi', 'page': 1, 'durationSeconds': 100}}
        meta.update(overrides)
        text = '<!-- transcript: ' + json.dumps(meta) + ' -->\n# 首播\n' + body
        return parse_transcript(text, {'sessions': [{'id': 's1', 'sources': [{'id': 'BV1eiXRYHEsi'}]}]})

    def test_manual_topic_split_preserves_text_and_time(self):
        result = self.document('## 问好\n[00:00.000 --> 00:12.500] 大家好！\n## 自我介绍\n[00:12.500 --> 00:30.000] 我是三理。')
        self.assertEqual(len(result['topics']), 2)
        self.assertEqual(result['topics'][1]['start'], 12.5)
        self.assertEqual(result['topics'][1]['segments'][0]['text'], '我是三理。')

    def test_export_excludes_internal_metadata(self):
        result = self.document(
            '## 问好\n[00:00 --> 00:10] 大家好！',
            rawRun='local-run', model='local-model', review={'device': 'local-device'},
            source={'bvid': 'BV1eiXRYHEsi', 'page': 1, 'durationSeconds': 100,
                    'audioFile': '/private/audio.m4a'},
        )
        self.assertEqual(set(result), {'schemaVersion', 'sessionId', 'status', 'timing', 'source', 'topics'})
        self.assertEqual(set(result['source']), {'bvid', 'page', 'durationSeconds'})

    def test_rejects_overlap_or_out_of_range(self):
        for body in ['## 话题\n[00:00 --> 00:20] 一\n[00:19 --> 00:30] 二', '## 话题\n[00:50 --> 01:59] 一', '## 话题\n[00:20 --> 00:10] 一']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.document(body)

    def test_rejects_missing_topic_and_wrong_recording(self):
        with self.assertRaises(ValueError):
            self.document('[00:00 --> 00:10] 一')
        with self.assertRaises(ValueError):
            self.document('## 空话题')
        with self.assertRaises(ValueError):
            self.document('## 话题\n[00:00 --> 00:10] 一', source={'bvid': 'other'})


if __name__ == '__main__':
    unittest.main()
