"""Keep reviewed community recordings attached to existing broadcast identities."""
import copy
import json
from pathlib import Path
import re
import time
import urllib.request
from urllib.parse import urlencode

CONFIG = Path(__file__).with_name('resources') / 'additional_recordings.json'


def request_data(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0',
                                                  'Referer': 'https://www.bilibili.com/'})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get('code') != 0 or not isinstance(payload.get('data'), dict):
        raise ValueError('Cannot read public recording metadata: ' + url)
    return payload['data']


def fetch_collection(config, fetch=request_data):
    """Read every page and reject incomplete or changing collection snapshots."""
    source = config['source']
    found, total, page = [], None, 1
    while total is None or len(found) < total:
        query = urlencode({'mid': source['mid'], 'season_id': source['seasonId'],
                           'sort_reverse': 'false', 'page_num': page, 'page_size': 100})
        data = fetch('https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?' + query)
        meta = data['meta']
        if meta['mid'] != source['mid'] or meta['season_id'] != source['seasonId']:
            raise ValueError('Unexpected recording collection')
        count = data['page']['total']
        if total is not None and count != total:
            raise ValueError('Collection changed during pagination')
        total = count
        batch = [row['bvid'] for row in data['archives']]
        if not batch and len(found) < total:
            raise ValueError('Incomplete recording collection')
        found.extend(batch)
        if len(set(found)) != len(found) or len(found) > total:
            raise ValueError('Duplicate or inconsistent collection pages')
        page += 1
    return {'total': total, 'bvids': found}


def refresh_metadata(config):
    """Refresh the full collection and retain reviewed uploads outside it."""
    collection = fetch_collection(config)
    result = {}
    ids = set(collection['bvids']) | {r['bvid'] for r in config['recordings']}
    for bvid in sorted(ids):
        data = request_data('https://api.bilibili.com/x/web-interface/view?bvid=' + bvid)
        if data.get('bvid') != bvid or data.get('owner', {}).get('mid') != config['source']['mid']:
            raise ValueError('Cannot verify additional recording: ' + bvid)
        result[bvid] = {'title': data['title'], 'durationSeconds': data['duration'],
                       'ownerId': data['owner']['mid'],
                       'pages': [{key: page[key] for key in ('page', 'part', 'duration')}
                                 for page in data['pages']]}
        time.sleep(.3)
    return {'collection': collection, 'videos': result}


def discover_entries(raw, config, snapshot):
    """Match new timestamped uploads only to independently established sessions."""
    from export_data import build_catalog
    from merge_supplement import timestamp, similarity
    reviewed = {r['bvid'] for r in config['recordings']} | set(config.get('excludedVideos', {}))
    sessions = build_catalog(raw)['sessions']
    entries, unresolved = [], []
    for bvid in snapshot.get('collection', {}).get('bvids', []):
        if bvid in reviewed:
            continue
        video = snapshot['videos'][bvid]
        day = re.search(r'(20\d{2})[.年-]?(\d{2})[.月-]?(\d{2})', video['title'])
        parts = video['pages']
        starts = [re.fullmatch(r'(\d{2})\.(\d{2}) (\d{2}:\d{2}:\d{2})',
                              p['part'].replace('：', ':')) for p in parts]
        candidates = []
        if day and parts and all(starts) and re.match(r'^【三理(?:Mit3uri)?\s*录播】', video['title']):
            try:
                times = [timestamp(f'{day[1]}-{m[1]}-{m[2]}T{m[3]}+08:00') for m in starts]
            except ValueError:
                times = []
            if times and all(0 <= times[i] - times[i-1] - parts[i-1]['duration'] <= 300
                             for i in range(1, len(times))):
                title = video['title'].replace(day[0], '')
                for session in sessions:
                    start = timestamp(session['startedAt'])
                    duration = session['liveDurationSeconds']
                    if start and duration and 0 <= times[0] - start <= 600 \
                            and times[-1] + parts[-1]['duration'] <= start + duration + 120 \
                            and similarity(title, session['title']) >= .75:
                        candidates.append(session['id'])
        if len(candidates) != 1:
            unresolved.append(bvid)
            continue
        entries.append(dict(video, bvid=bvid, sessionId=candidates[0],
                            recordingPages=[p['page'] for p in parts]))
    if unresolved:
        raise ValueError('Collection recordings need scope/part matching: ' + ', '.join(unresolved))
    return entries


def merge_additional_recordings(raw, config, metadata=None):
    """Add only reviewed links; selected parts determine this session's coverage."""
    raw = copy.deepcopy(raw)
    source = config['source']
    snapshot = metadata or {}
    videos = snapshot.get('videos', snapshot)
    collection = snapshot.get('collection')
    if collection and (len(set(collection['bvids'])) != collection['total']
                       or any(b not in videos for b in collection['bvids'])):
        raise ValueError('Incomplete collection metadata')
    entries = config['recordings'] + discover_entries(raw, config, snapshot)
    sessions = {s['session_id'] for s in raw['sessions'] if s.get('included_in_total')}
    known = {r['bvid']: r for r in raw['recordings']}
    added = []
    for entry in entries:
        bvid, target = entry['bvid'], entry['sessionId']
        if bvid in config.get('excludedVideos', {}):
            raise ValueError('External recording cannot be imported: ' + bvid)
        if target not in sessions:
            raise ValueError('Missing reviewed session: ' + target)
        if bvid in known:
            if known[bvid]['session_id'] != target:
                raise ValueError('Conflicting recording assignment: ' + bvid)
            continue
        details = videos.get(bvid, entry)
        if details.get('ownerId', source['mid']) != source['mid']:
            raise ValueError('Unexpected recording owner: ' + bvid)
        # Part order and labels are evidence for the reviewed session assignment.
        expected = [(p['page'], p['part']) for p in entry['pages']]
        actual = [(p['page'], p['part']) for p in details['pages']]
        if actual != expected:
            raise ValueError('Recording parts changed; review required: ' + bvid)
        parts = {p['page']: p for p in details['pages']}
        selected = entry['recordingPages']
        if not selected or len(set(selected)) != len(selected) or any(p not in parts for p in selected):
            raise ValueError('Invalid reviewed recording parts: ' + bvid)
        coverage = sum(parts[p]['duration'] for p in selected)
        if coverage <= 0 or details['durationSeconds'] <= 0:
            raise ValueError('Invalid recording duration: ' + bvid)
        recording = {'bvid': bvid, 'session_id': target, 'title': details['title'],
                     'duration_seconds': details['durationSeconds'],
                     'session_duration_seconds': coverage,
                     'source_priority': source['priority'], 'source_mid': source['mid'],
                     'source_up_name': source['name'], 'source_url': source['url'],
                     'match_method': 'reviewed_recording_parts', 'match_confidence': 'high'}
        raw['recordings'].append(recording)
        known[bvid] = recording
        added.append({'bvid': bvid, 'session': target})
    return raw, added
