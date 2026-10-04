"""Extend audited session identities with independently timed live history and new videos."""
import copy
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import re
from pathlib import Path

TZ = timezone(timedelta(hours=8))


def timestamp(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return int(parsed.timestamp())


def title_key(value):
    value = re.sub(r'【[^】]*】|\[[^\]]*\]', '', value).lower()
    value = re.sub(r'三理mit3uri|三理|直播回放|录播|弹幕版', '', value)
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', value)


def similarity(left, right):
    a, b = title_key(left), title_key(right)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0


def merge_supplement(raw, supplement):
    raw = copy.deepcopy(raw)
    errors = [m for m in supplement['history'] if 'error' in m]
    if errors:
        raise ValueError('Incomplete live-history refresh: ' + ', '.join(m['month'] for m in errors))
    sessions = raw['sessions']
    evidence = defaultdict(list)
    recordings = defaultdict(list)
    for row in raw['evidence']:
        evidence[row['session_id']].append(row)
    for row in raw['recordings']:
        recordings[row['session_id']].append(row)
    cutoff = max(s['live_date'] for s in sessions)
    last_catalog_start = max((s.get('start_timestamp') or 0) for s in sessions)
    report = {'newSessions': [], 'newRecordings': [], 'unresolvedRecordings': [], 'skippedRecordings': []}
    history = sorted((row for month in supplement['history'] for row in month['sessions']), key=lambda row: row['start_time'])
    for live in history:
        start, end = timestamp(live['start_time']), timestamp(live['end_time'])
        if start is None or (end is not None and end - start <= 360):
            continue
        day = datetime.fromtimestamp(start, TZ).date().isoformat()
        exact = [s for s in sessions if any(abs((e.get('start_timestamp') or 0) - start) <= 90 for e in evidence[s['session_id']])
                 or (s.get('start_time_precision') == 'second' and abs((s.get('start_timestamp') or 0) - start) <= 90)]
        chosen = min(exact, key=lambda s: abs((s.get('start_timestamp') or 0) - start)) if exact else None
        if chosen is None:
            matches = [s for s in sessions if s['live_date'] == day
                       and s.get('start_time_precision') != 'second'
                       and similarity(s['title'], live['title'] or '') >= .88
                       and end is not None and s.get('duration_seconds')
                       and abs((end - start) - s['duration_seconds']) <= max(600, .15 * s['duration_seconds'])]
            if len(matches) == 1:
                chosen = matches[0]
        if chosen is None and (day > cutoff or (day == cutoff and start > last_catalog_start)):
            chosen = {'session_id': f'MIT3URI-LIVE-{start}', 'title': live['title'] or '直播',
                      'live_date': day, 'start_time_precision': 'second', 'start_timestamp': start,
                      'start_time': datetime.fromtimestamp(start, TZ).isoformat(),
                      'duration_seconds': end - start if end else None,
                      'included_in_total': 1, 'preferred_bvid_mode': None,
                      'catalog_generated_at': supplement['fetchedAt']}
            sessions.append(chosen)
            report['newSessions'].append(chosen['session_id'])
        if chosen is not None:
            ev = {'session_id': chosen['session_id'], 'source': 'qianqiu', 'native_id': str(start),
                  'start_timestamp': start, 'end_timestamp': end, 'excluded_short': 0}
            raw['evidence'].append(ev)
            evidence[chosen['session_id']].append(ev)
    known = {r['bvid'] for r in raw['recordings']}
    excluded = set(supplement['excludedBvids'])
    overrides = json.loads(Path(__file__).with_name('recording_overrides.json').read_text())
    for row in supplement['recordings']:
        if row['bvid'] in known or row['bvid'] in excluded:
            continue
        if row['duration_seconds'] <= 360 or not row.get('parsed_day'):
            report['skippedRecordings'].append({'bvid': row['bvid'], 'title': row['title'], 'reason': 'short_or_no_live_date'})
            continue
        candidates = []
        hint = timestamp(row.get('parsed_start'))
        for session in sessions:
            if session['live_date'] != row['parsed_day']:
                continue
            title_score = similarity(session['title'], row['display_title'])
            reference_duration = session.get('duration_seconds') or 0
            ratio = min(reference_duration, row['duration_seconds']) / max(reference_duration, row['duration_seconds']) if reference_duration else 0
            start = session.get('start_timestamp')
            if hint and start and row['parsed_precision'] in ('hour', 'minute', 'second'):
                tolerance = 3600 if row['parsed_precision'] == 'hour' else 600
                if abs(hint - start) > tolerance:
                    continue
            if title_score >= .75 or (ratio >= .94 and reference_duration > 1800):
                candidates.append((title_score * 2 + ratio, title_score, ratio, session))
        override = overrides.get(row['bvid'])
        if override:
            target = next((s for s in sessions if s['session_id'] == override['sessionId']), None)
            if target is None:
                raise ValueError('Missing audited segment target: ' + row['bvid'])
            candidates = [(3, 1, 1, target)]
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .2):
            report['unresolvedRecordings'].append({'bvid': row['bvid'], 'title': row['title'],
                                                  'candidates': [x[3]['session_id'] for x in candidates]})
            continue
        _, title_score, ratio, chosen = candidates[0]
        item = {'bvid': row['bvid'], 'session_id': chosen['session_id'], 'title': row['title'],
                'duration_seconds': row['duration_seconds'], 'source_priority': row['source_priority'],
                'source_mid': row['source_mid'], 'source_up_name': row['up_name'], 'source_url': row['source_url'],
                'match_method': 'same_source_segment_verified' if override and override['segment'] else 'live_history_title_duration',
                'match_confidence': 'high' if title_score >= .95 and ratio >= .75 else 'medium'}
        raw['recordings'].append(item)
        recordings[chosen['session_id']].append(item)
        if override and override['segment']:
            for peer in recordings[chosen['session_id']]:
                if peer['source_mid'] == row['source_mid']:
                    peer['match_method'] = 'same_source_segment_verified'
        known.add(row['bvid'])
        report['newRecordings'].append({'bvid': row['bvid'], 'session': chosen['session_id'], 'titleScore': round(title_score, 3), 'durationRatio': round(ratio, 3)})
    raw['supplement'] = {key: supplement[key] for key in ['fetchedAt', 'vtbStarts', 'overrides']}
    raw['exportedAt'] = supplement['fetchedAt']
    return raw, report
