"""Read only public replay metadata and matching broadcast markers from libot2.

Run on the source host through stdin. No application imports or DB writes.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

db = Path.home() / "libot2/data/libot.db"
with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("BEGIN")
    sessions = [dict(row) for row in conn.execute(
        "SELECT * FROM mit3uri_replay_session WHERE included_in_total = 1"
    )]
    recordings = [dict(row) for row in conn.execute(
        "SELECT r.* FROM mit3uri_replay_recording r JOIN mit3uri_replay_session s "
        "USING(session_id) WHERE s.included_in_total = 1"
    )]
    evidence = [dict(row) for row in conn.execute(
        "SELECT e.* FROM mit3uri_replay_evidence e JOIN mit3uri_replay_session s "
        "USING(session_id) WHERE s.included_in_total = 1 AND e.excluded_short = 0"
    )]
    # Only broadcast state markers are exported; viewer identities and chat stay private.
    markers = [dict(row) for row in conn.execute(
        "SELECT cmd, timestamp FROM event WHERE room_id = 1967216004 "
        "AND cmd IN ('LIVE', 'PREPARING') ORDER BY timestamp, id"
    )]
print(json.dumps({"exportedAt": datetime.now(timezone.utc).isoformat(),
                  "sessions": sessions, "recordings": recordings,
                  "evidence": evidence, "markers": markers}, ensure_ascii=False))
