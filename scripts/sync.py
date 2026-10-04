"""Refresh public replay metadata, preserving the source database and audited identities."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
from export_data import build_catalog
from merge_supplement import merge_supplement
from additional_recordings import CONFIG, merge_additional_recordings, refresh_metadata

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host', default='ubuntu-server', help='SSH host alias')
parser.add_argument('--cached', action='store_true', help='Rebuild from the last local source snapshots')
args = parser.parse_args()
if args.host.startswith('-'):
    parser.error('host must be an SSH alias')
cache = ROOT / '.cache'
cache.mkdir(exist_ok=True)
additional_config = json.loads(CONFIG.read_text())
additional_cache = cache / 'additional-recordings.json'
ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', args.host]

def remote_script(name, command):
    result = subprocess.run(ssh + [command], input=(ROOT / 'scripts' / name).read_text(),
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

if args.cached:
    raw = json.loads((cache / 'replay-source-latest.json').read_text())
    supplement = json.loads((cache / 'supplement.json').read_text())
    additional_metadata = json.loads(additional_cache.read_text()) if additional_cache.exists() else {}
else:
    temporary = subprocess.run(ssh + ['mktemp -d /tmp/mit3uri-replay.XXXXXX'], capture_output=True,
                               text=True, check=True).stdout.strip()
    if not re.fullmatch(r'/tmp/mit3uri-replay\.[A-Za-z0-9]+', temporary):
        raise ValueError('Unexpected temporary directory')
    raw_path = shlex.quote(temporary + '/recordings.json')
    print('Refreshing six recording sources…', flush=True)
    subprocess.run(ssh + ['cd ~/libot2 && .venv/bin/python scripts/collect_mit3uri_replays.py '
                          '--raw-only --request-interval 0.8 --output ' + raw_path], check=True)
    print('Reading audited sessions and live history…', flush=True)
    raw = remote_script('read_remote.py', 'python3 -')
    supplement = remote_script('read_supplement.py', 'cd ~/libot2 && .venv/bin/python - ' + raw_path)
    print('Refreshing the complete 最后--年 collection…', flush=True)
    additional_metadata = refresh_metadata(additional_config)
    additional_cache.write_text(json.dumps(additional_metadata, ensure_ascii=False))
    # Temporary collector output contains only public metadata and can expire with /tmp.
    (cache / 'replay-source-latest.json').write_text(json.dumps(raw, ensure_ascii=False))
    (cache / 'supplement.json').write_text(json.dumps(supplement, ensure_ascii=False))
merged, report = merge_supplement(raw, supplement)
(cache / 'import-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
if report['unresolvedRecordings']:
    raise ValueError('Unresolved recording matches; inspect .cache/import-report.json before publishing')
merged, additions = merge_additional_recordings(merged, additional_config, additional_metadata)
report['additionalRecordings'] = additions
if 'collection' in additional_metadata:
    report['additionalCollection'] = additional_metadata['collection']
(cache / 'import-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
from session_notes import apply_notes
catalog = apply_notes(build_catalog(merged))
(cache / 'merged-source.json').write_text(json.dumps(merged, ensure_ascii=False))
destination = ROOT / 'site/data/catalog.json'
temporary = destination.with_suffix('.json.tmp')
temporary.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')) + '\n')
temporary.replace(destination)
print(f"Updated {len(catalog['sessions'])} sessions; source refresh: {catalog['catalogGeneratedAt']}")
