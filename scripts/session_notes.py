"""Apply curated summaries and tags without inferring labels for other sessions."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def apply_notes(catalog):
    notes = json.loads((ROOT / 'content/session-notes.json').read_text())
    for record in catalog['sessions']:
        note = notes.get(record['id'])
        if note is None:
            continue
        if set(note) - {'summary', 'tags'}:
            raise ValueError('Unsupported session note field')
        if 'summary' in note and not isinstance(note['summary'], str):
            raise ValueError('Summary must be text')
        if 'tags' in note and (not isinstance(note['tags'], list) or any(not isinstance(tag, str) or not tag.strip() for tag in note['tags'])):
            raise ValueError('Tags must be non-empty strings')
        record.update(note)
    return catalog


if __name__ == '__main__':
    path = ROOT / 'site/data/catalog.json'
    catalog = apply_notes(json.loads(path.read_text()))
    path.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':'))+'\n')
