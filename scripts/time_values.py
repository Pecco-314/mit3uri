"""Parse explicit recording timestamps without inventing missing seconds."""
from datetime import datetime, timedelta, timezone
import re

TZ = timezone(timedelta(hours=8))


def parse_recording_time(title):
    filename = re.search(r'录制-(\d+)-(\d{8})-(\d{6})(?:-(\d{3}))?', title)
    if filename:
        try:
            value = datetime.strptime(filename[2] + filename[3], '%Y%m%d%H%M%S').replace(
                tzinfo=TZ, microsecond=int(filename[4] or 0) * 1000)
        except ValueError:
            return None
        return {'startedAt': value.isoformat(), 'precision': 'second', 'roomId': int(filename[1])}
    match = re.search(r'(20\d{2})-(\d{1,2})-(\d{1,2})\s+(\d{1,2})[_:](\d{2})(?:[_:](\d{2}))?', title)
    match = match or re.search(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日\s*(\d{1,2})点\s*(\d{1,2})分(?:\s*(\d{1,2})秒)?', title)
    if not match:
        return None
    try:
        value = datetime(*(int(v or 0) for v in match.groups()), tzinfo=TZ)
    except ValueError:
        return None
    return {'startedAt': value.isoformat(), 'precision': 'second' if match[6] is not None else 'minute'}
