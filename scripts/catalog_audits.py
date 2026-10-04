"""Apply reviewed recording identities and time evidence to immutable source snapshots."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
from statistics import median
from time_values import parse_recording_time

AUDITS = Path(__file__).resolve().parents[1] / 'content/time-audits.json'


def apply_audits(raw, audits=None):
    audits = json.loads(AUDITS.read_text()) if audits is None else audits
    result = copy.deepcopy(raw)
    sessions = {s['session_id']: s for s in result['sessions']}
    aliases = {}

    def check(sid, date, bvid):
        if sid not in sessions or sessions[sid]['live_date'] != date:
            raise ValueError('Audited session date changed: ' + sid)
        matches = [r for r in result['recordings'] if r['session_id'] == sid and r['bvid'] == bvid]
        if len(matches) != 1:
            raise ValueError('Audited recording assignment changed: ' + bvid)
        return matches[0]

    def retire(sid):
        if any(e['session_id'] == sid and not e['excluded_short'] for e in result['evidence']):
            raise ValueError('Cannot retire a session with independent evidence: ' + sid)
        if any(r['session_id'] == sid for r in result['recordings']):
            raise ValueError('Cannot retire a session with remaining recordings: ' + sid)
        sessions[sid]['included_in_total'] = 0

    for item in audits.get('excludedSessions', []):
        sid = item['sessionId']
        if sid not in sessions:
            continue
        if item['roomId'] == audits['roomId']:
            raise ValueError('Cannot exclude own-room recording')
        for bvid in item['bvids']:
            check(sid, item['date'], bvid)
        result['recordings'] = [r for r in result['recordings']
                                if not (r['session_id'] == sid and r['bvid'] in item['bvids'])]
        retire(sid)

    for item in audits.get('merges', []):
        old, target = item['fromSession'], item['toSession']
        if old not in sessions:
            continue
        recording = check(old, item['date'], item['bvid'])
        check(target, item['date'], item['targetAnchorBvid'])
        recording.update(session_id=target, match_method='reviewed_tail_segment', match_confidence='high')
        retire(old)
        aliases[old] = target

    for item in audits.get('splits', []):
        old = item['fromSession']
        if old not in sessions:
            continue
        recording = check(old, item['date'], item['bvid'])
        assigned = set()
        for part in item['parts']:
            check(part['sessionId'], part['date'], part['targetAnchorBvid'])
            pages = part['pages']
            if not pages or assigned.intersection(pages) or len(set(pages)) != len(pages):
                raise ValueError('Overlapping audited parts: ' + item['bvid'])
            assigned.update(pages)
            result['recordings'].append(dict(recording, session_id=part['sessionId'],
                recording_pages=pages, session_duration_seconds=part['coverageSeconds'],
                match_method='reviewed_cross_session_parts', match_confidence='high'))
        result['recordings'].remove(recording)
        retire(old)
        aliases[old] = item['aliasTo']

    starts = {}
    for sid, item in audits.get('starts', {}).items():
        if sid not in sessions:
            continue
        check(sid, item['date'], item['anchorBvid'])
        if item['startedAt'][:10] != item['date'] or item['precision'] not in ('minute', 'second'):
            raise ValueError('Invalid audited time: ' + sid)
        start = datetime.fromisoformat(item['startedAt'])
        if item['timeEvidence'] == 'verified_replay_clock':
            frames = item['evidence']['frames']
            if len(frames) < 2 or max(f['offsetSeconds'] for f in frames) - min(f['offsetSeconds'] for f in frames) < 60:
                raise ValueError('Insufficient clock observations: ' + sid)
            origins = [datetime.fromisoformat(item['date'] + 'T' + f['clock'] + '+08:00')
                       - timedelta(seconds=f['offsetSeconds']) for f in frames]
            normalized = [t.replace(second=0, microsecond=0) if item['precision'] == 'minute'
                          else t.replace(microsecond=0) for t in origins]
            if any(t != start for t in normalized) or (max(origins) - min(origins)).total_seconds() > 1:
                raise ValueError('Conflicting clock observations: ' + sid)
            if item.get('endedAt'):
                raise ValueError('Clock evidence does not establish live duration: ' + sid)
        elif item['timeEvidence'] == 'live_history':
            if datetime.fromisoformat(item['endedAt']) <= start:
                raise ValueError('Invalid audited live interval: ' + sid)
        elif item['timeEvidence'] == 'aligned_recording_part':
            evidence = item['evidence']
            source = check(sid, item['date'], evidence['recordingBvid'])
            if source['source_mid'] != evidence['uploaderId']:
                raise ValueError('Audited part uploader changed: ' + sid)
            parsed = parse_recording_time(evidence['partTitle'])
            if not parsed or parsed['precision'] != 'second' or parsed.get('roomId', audits.get('roomId')) != audits.get('roomId'):
                raise ValueError('Missing explicit part timestamp: ' + sid)
            recorded = datetime.fromisoformat(parsed['startedAt'])
            if recorded != datetime.fromisoformat(evidence['recordingStartedAt']):
                raise ValueError('Part timestamp disagrees with evidence: ' + sid)
            matches = evidence['audioMatches']
            offsets = [m.get('referenceOffset', m.get('officialOffset')) - m['communityOffset'] for m in matches]
            if len(offsets) < 2 or max(offsets) - min(offsets) > .2:
                raise ValueError('Conflicting audio alignment: ' + sid)
            origin = recorded - timedelta(seconds=median(offsets))
            normalized = origin.replace(second=0, microsecond=0) if item['precision'] == 'minute' else origin.replace(microsecond=0)
            if normalized != start or item.get('endedAt'):
                raise ValueError('Invalid aligned start: ' + sid)
        else:
            raise ValueError('Unsupported audited time evidence: ' + sid)
        starts[sid] = item
    result['auditedStarts'] = starts
    result['sessionAliases'] = aliases
    return result
