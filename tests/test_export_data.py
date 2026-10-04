"""Protect the boundary between inferred catalog times and publishable facts."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from export_data import build_catalog, recording_title_start
from time_values import parse_recording_time


class TimePolicyTest(unittest.TestCase):
    def setUp(self):
        self.raw = {
            "exportedAt": "2026-10-03T00:00:00+00:00",
            "sessions": [{"session_id": "MIT3URI-0001", "title": "测试场次", "live_date": "2026-01-01",
                          "start_time_precision": "second", "start_timestamp": 1000,
                          "included_in_total": 1, "preferred_bvid_mode": "single",
                          "catalog_generated_at": "2026-08-05T19:25:48+08:00"}],
            "recordings": [],
            "evidence": [{"session_id": "MIT3URI-0001", "source": "database", "excluded_short": 0,
                          "start_timestamp": 1000, "end_timestamp": 2000}],
            "markers": [{"cmd": "LIVE", "timestamp": 1000}, {"cmd": "PREPARING", "timestamp": 2000}],
        }

    def record(self):
        return build_catalog(self.raw)["sessions"][0]

    def test_original_events_allow_time_and_duration(self):
        self.assertTrue(self.record()["startedAt"].endswith("+08:00"))
        self.assertEqual(self.record()["liveDurationSeconds"], 1000)

    def test_hour_and_minute_estimates_are_never_exported(self):
        for precision in ("hour", "minute", "date"):
            self.raw["sessions"][0]["start_time_precision"] = precision
            self.assertIsNone(self.record()["startedAt"])
            self.assertIsNone(self.record()["liveDurationSeconds"])

    def test_second_precision_without_original_marker_is_not_proof(self):
        self.raw["markers"] = []
        self.assertIsNone(self.record()["startedAt"])

    def test_unverified_vtb_fallback_and_title_hints_are_not_proof(self):
        for source in ("vtbcat", "replay_title"):
            self.raw["evidence"][0]["source"] = source
            self.assertIsNone(self.record()["startedAt"])

    def test_audited_history_provides_start_and_duration(self):
        self.raw["evidence"][0]["source"] = "danmakus"
        self.raw["markers"] = []
        self.assertEqual(self.record()["timeEvidence"], "danmakus_history")
        self.assertEqual(self.record()["liveDurationSeconds"], 1000)

    def test_verified_vtb_start_at_is_accepted(self):
        self.raw["evidence"][0].update(source="vtbcat", native_id="123")
        self.raw["supplement"] = {"vtbStarts": [{"id": "123", "start_time": "1970-01-01T08:16:40+08:00"}]}
        self.assertEqual(self.record()["timeEvidence"], "vtbcat_start_at")

    def test_recording_length_does_not_require_exact_live_start(self):
        self.raw["sessions"][0]["start_time_precision"] = "hour"
        self.raw["recordings"] = [{"session_id": "MIT3URI-0001", "bvid": "BV1234567890", "title": "录播",
                                   "source_mid": 123, "source_up_name": "来源", "source_priority": 1,
                                   "duration_seconds": 1234, "match_confidence": "high", "match_method": "title_exact_time"}]
        self.assertIsNone(self.record()["startedAt"])
        self.assertIsNone(self.record()["liveDurationSeconds"])
        self.assertEqual(self.record()["recordingDurationSeconds"], 1234)

    def test_different_catalog_start_is_withheld(self):
        self.raw["sessions"][0]["start_timestamp"] = 900
        self.assertIsNone(self.record()["startedAt"])

    def test_open_session_has_no_live_duration(self):
        self.raw["markers"] = self.raw["markers"][:1]
        self.assertIsNotNone(self.record()["startedAt"])
        self.assertIsNone(self.record()["liveDurationSeconds"])

    def test_official_account_wins_over_source_priority(self):
        base = {"session_id": "MIT3URI-0001", "bvid": "BV1234567890", "title": "录播",
                "source_mid": 123, "source_up_name": "其他来源", "source_priority": 1,
                "duration_seconds": 999, "match_confidence": "high", "match_method": "title_exact_time"}
        official = dict(base, bvid="BV1234567891", source_mid=2030198123, source_priority=99)
        self.raw["recordings"] = [base, official]
        sources = self.record()["sources"]
        self.assertTrue(sources[0]["official"])
        self.assertEqual(len(sources), 2)

    def test_excluded_sessions_stay_out(self):
        self.raw["sessions"][0]["included_in_total"] = 0
        self.assertEqual(build_catalog(self.raw)["sessions"], [])

    def test_public_catalog_does_not_include_raw_or_estimated_fields(self):
        catalog = json.loads((ROOT / "site/data/catalog.json").read_text())
        notes = json.loads((ROOT / "content/session-notes.json").read_text())
        for row in catalog["sessions"]:
            self.assertNotIn("start_timestamp", row)
            self.assertNotIn("start_time_precision", row)
            if row["startedAt"]:
                self.assertIn(row["timeEvidence"], {"bilibili_live_event", "vtbcat_start_at", "live_history", "danmakus_history", "audited_recording_timestamp", "qingli_recording_title", "verified_replay_clock", "aligned_recording_part"})
            if row["liveDurationSeconds"] is not None:
                self.assertIsNotNone(row["startedAt"])
            self.assertEqual(row["tags"], notes.get(row["id"], {}).get("tags", []))
            self.assertEqual(row["summary"], notes.get(row["id"], {}).get("summary"))
            self.assertIsNone(row["transcript"])


class RecordingTitleTimeTest(unittest.TestCase):
    def test_explicit_zero_seconds_are_distinct_from_minute_precision(self):
        self.assertEqual(parse_recording_time('2025年08月06日22点06分')['precision'], 'minute')
        self.assertEqual(parse_recording_time('2025年08月06日22点06分00秒')['precision'], 'second')

    def test_filename_seconds_retain_original_milliseconds_and_room(self):
        parsed = parse_recording_time('录制-1967216004-20250807-210259-051-我是美女主播！')
        self.assertEqual(parsed['startedAt'], '2025-08-07T21:02:59.051000+08:00')
        self.assertEqual(parsed['roomId'], 1967216004)
        self.assertEqual(parsed['precision'], 'second')

    def parse(self, title, uid=1702090167):
        return recording_title_start({"title": title, "source_mid": uid})

    def test_second_timestamp(self):
        self.assertEqual(self.parse("三理和大家的初次见面！2025-03-01 20_26_42"), "2025-03-01T20:26:42+08:00")

    def test_chinese_minute_timestamp(self):
        self.assertEqual(self.parse("【三理Mit3uri】计划有变！2025年12月13日17点57分"), "2025-12-13T17:57:00+08:00")

    def test_hour_only_and_invalid_time_are_rejected(self):
        self.assertIsNone(self.parse("2025年03月01日20点场"))
        self.assertIsNone(self.parse("2025-02-30 20_26_42"))
        self.assertIsNone(self.parse("2025-03-01 25_26_42"))

    def test_other_uploaders_are_not_implicitly_trusted(self):
        self.assertIsNone(self.parse("2025-03-01 20_26_42", uid=123))


if __name__ == "__main__":
    unittest.main()
