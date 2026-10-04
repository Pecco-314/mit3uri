"""Publish witnessed live times and recording lengths, keeping their provenance separate."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from time_values import parse_recording_time

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
OFFICIAL_UID = 2030198123
TIMESTAMP_UPLOADER_UID = 1702090167


def recording_title_start(recording):
    """Parse explicit minute/second timestamps from the designated recording uploader."""
    if recording["source_mid"] != TIMESTAMP_UPLOADER_UID:
        return None
    value = parse_recording_time(recording['title'])
    return value['startedAt'] if value else None


def build_catalog(raw):
    from catalog_audits import apply_audits
    raw = apply_audits(raw)
    recordings, evidence = defaultdict(list), defaultdict(list)
    for row in raw["recordings"]:
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", row["bvid"]):
            raise ValueError("Invalid BVID")
        recordings[row["session_id"]].append(row)
    for row in raw["evidence"]:
        if not row["excluded_short"]:
            evidence[row["session_id"]].append(row)
    live = {int(r["timestamp"]) for r in raw["markers"] if r["cmd"] == "LIVE" and r["timestamp"]}
    stop = {int(r["timestamp"]) for r in raw["markers"] if r["cmd"] == "PREPARING" and r["timestamp"]}
    sessions = []
    for row in raw["sessions"]:
        if not row["included_in_total"]:
            continue
        candidates = []
        supplement = raw.get("supplement", {})
        vtb_starts = {e["id"]: int(datetime.fromisoformat(e["start_time"]).timestamp())
                      for e in supplement.get("vtbStarts", [])}
        for item in evidence[row["session_id"]]:
            start_ts = item.get("start_timestamp")
            if not start_ts:
                continue
            source = item["source"]
            agrees = row["start_time_precision"] == "second" and start_ts == row["start_timestamp"]
            if source == "database" and start_ts in live and agrees:
                candidates.append((0, start_ts, "bilibili_live_event", item))
            elif source == "vtbcat" and agrees and vtb_starts.get(item.get("native_id")) == start_ts:
                candidates.append((1, start_ts, "vtbcat_start_at", item))
            elif source == "qianqiu":
                candidates.append((2, start_ts, "live_history", item))
            elif source == "danmakus" and agrees:
                candidates.append((3, start_ts, "danmakus_history", item))
        selected = min(candidates, key=lambda value: (value[0], value[1])) if candidates else None
        manual = next((o for o in supplement.get("overrides", {}).get("start_time_overrides", [])
                       if any(r["bvid"] == o["bvid"] for r in recordings[row["session_id"]])), None)
        start = datetime.fromtimestamp(selected[1], TZ).isoformat() if selected else None
        time_evidence = selected[2] if selected else None
        start_precision = 'second' if selected else None
        if manual and not selected:
            start = manual["start_time"]
            time_evidence = "audited_recording_timestamp"
            start_precision = 'second'
        if start is None:
            title_starts = {value for r in recordings[row["session_id"]]
                            if (value := recording_title_start(r)) and value[:10] == row["live_date"]}
            if len(title_starts) == 1:
                start = title_starts.pop()
                time_evidence = "qingli_recording_title"
                precisions = [parse_recording_time(r['title'])['precision']
                              for r in recordings[row['session_id']] if recording_title_start(r) == start]
                start_precision = 'second' if 'second' in precisions else 'minute'
        audited = raw['auditedStarts'].get(row['session_id'])
        if audited and not selected:
            start = audited['startedAt']
            time_evidence = audited['timeEvidence']
            start_precision = audited['precision']
        duration = None
        duration_evidence = None
        if selected:
            for _, start_ts, kind, item in sorted(candidates, key=lambda value: (value[0], value[1])):
                end_ts = item.get("end_timestamp")
                if abs(start_ts - selected[1]) > 90 or not end_ts or end_ts <= start_ts:
                    continue
                if item["source"] == "database" and end_ts not in stop:
                    continue
                duration = end_ts - start_ts
                duration_evidence = kind
                break
        if audited and not selected and audited.get('endedAt'):
            duration = int((datetime.fromisoformat(audited['endedAt']) - datetime.fromisoformat(start)).total_seconds())
            duration_evidence = audited['timeEvidence']
        sources = []
        for r in sorted(recordings[row["session_id"]], key=lambda r: (r["source_mid"] != OFFICIAL_UID, r["source_priority"], r["bvid"])):
            sources.append({"id": r["bvid"], "title": r["title"],
                            "url": "https://www.bilibili.com/video/" + r["bvid"] + "/" +
                                   ("?p=" + str(r['recording_pages'][0]) if r.get('recording_pages') else ""),
                            "uploader": r["source_up_name"], "uploaderId": r["source_mid"],
                            "official": r["source_mid"] == OFFICIAL_UID,
                            "durationSeconds": r["duration_seconds"],
                            "matchConfidence": r["match_confidence"], "matchMethod": r["match_method"],
                            "segment": r["match_method"].startswith("same_source_segment") or r['match_method'] == 'reviewed_tail_segment',
                            **({'recordingPages': r['recording_pages']} if r.get('recording_pages') else {})})
        by_source = defaultdict(list)
        for recording in recordings[row["session_id"]]:
            by_source[recording["source_mid"]].append(recording)
        recording_duration = max((sum(r.get("session_duration_seconds", r["duration_seconds"]) for r in group)
                                  if any(r["match_method"].startswith("same_source_segment") for r in group)
                                  else max(r.get("session_duration_seconds", r["duration_seconds"]) for r in group)
                                  for group in by_source.values()), default=None)
        sessions.append({"id": row["session_id"], "title": row["title"],
                         "date": start[:10] if start else row["live_date"], "startedAt": start,
                         "timeEvidence": time_evidence, "durationEvidence": duration_evidence,
                         "startedAtPrecision": start_precision,
                         "liveDurationSeconds": duration, "recordingDurationSeconds": recording_duration, "sources": sources,
                         "preferredMode": row["preferred_bvid_mode"],
                         "summary": None, "transcript": None, "tags": [], "danmaku": None})
    sessions.sort(key=lambda r: (r["date"], r["startedAt"] or "", r["id"]))
    return {"schemaVersion": 1, "channel": {"name": "三理Mit3uri", "uid": OFFICIAL_UID, "roomId": 1967216004},
            "exportedAt": raw["exportedAt"],
            "catalogGeneratedAt": raw.get("supplement", {}).get("fetchedAt") or max(r["catalog_generated_at"] for r in raw["sessions"]),
            "timezone": "Asia/Shanghai", "sessionAliases": raw['sessionAliases'], "sessions": sessions}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "site/data/catalog.json")
    args = parser.parse_args()
    from session_notes import apply_notes
    catalog = apply_notes(build_catalog(json.loads(args.input.read_text())))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n")
    rows = catalog["sessions"]
    print(f"{len(rows)} sessions; {sum(bool(r['sources']) for r in rows)} with replays; "
          f"{sum(bool(r['startedAt']) for r in rows)} verified starts; "
          f"{sum(len(r['sources']) for r in rows)} links")
