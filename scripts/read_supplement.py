"""Read public live-history and normalized recording metadata on the libot2 host."""
import concurrent.futures
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import httpx

ROOT = Path.home() / 'libot2'
sys.path.insert(0, str(ROOT))
from scripts.build_mit3uri_replay_catalog import _load_raw

TZ = timezone(timedelta(hours=8))
raw_path = Path(sys.argv[1])
recordings, sources = _load_raw(raw_path)
old = json.loads((ROOT / 'data/mit3uri_replay_catalog.json').read_text())
overrides = json.loads((ROOT / 'scripts/resources/mit3uri_replay_session_merges.json').read_text())
excluded = [r['bvid'] for group in ['excluded_short_recording_sessions', 'excluded_external_recording_sessions']
            for session in old.get(group, []) for r in session.get('recordings', [])]
now = datetime.now(TZ)
months = [f'{year}-{month:02}' for year in range(2025, now.year + 1) for month in range(1, 13)
          if '2025-03' <= f'{year}-{month:02}' <= now.strftime('%Y-%m')]

def fetch_month(month):
    try:
        with httpx.Client(trust_env=False, timeout=40) as client:
            response = client.get('https://vr.qianqiuzy.cn/gift/live_sessions',
                                  params={'room_id': 1967216004, 'month': month})
            response.raise_for_status()
            data = response.json()
        if str(data.get('room_id')) != '1967216004' or str(data.get('month')).replace('-', '') != month.replace('-', ''):
            raise ValueError('Unexpected room or month')
        return {'month': month, 'sessions': [{key: row.get(key) for key in ['start_time', 'end_time', 'title']}
                                            for row in data['sessions']]}
    except Exception as error:
        return {'month': month, 'error': str(error)}

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    history = list(pool.map(fetch_month, months))
vtb = json.loads((ROOT / 'data/vtb_cat/2030198123/space.json').read_text())
vtb_starts = []
for row in vtb.get('Lives', []):
    if row.get('StartAt'):
        start = datetime.fromtimestamp(row['StartAt'], timezone.utc).replace(tzinfo=TZ)
        vtb_starts.append({'id': str(row['ID']), 'start_time': start.isoformat()})
print(json.dumps({'fetchedAt': now.isoformat(), 'recordings': recordings, 'sources': sources,
                  'history': history, 'vtbStarts': vtb_starts, 'overrides': overrides,
                  'excludedBvids': excluded}, ensure_ascii=False))
