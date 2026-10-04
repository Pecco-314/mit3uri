"""Compile manually editable topic transcripts into on-demand static JSON."""
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAMP = r"(?:\d{2,}:)?\d{2}:\d{2}(?:\.\d{1,3})?"
LINE = re.compile(rf"^\[({STAMP}) --> ({STAMP})\]\s+(.+)$")


def seconds(value):
    parts = [float(part) for part in value.split(":")]
    if any(p >= 60 for p in parts[1:]):
        raise ValueError(f"Invalid timestamp: {value}")
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def parse_transcript(text, catalog):
    lines = text.splitlines()
    if not lines or not lines[0].startswith("<!-- transcript: ") or not lines[0].endswith(" -->"):
        raise ValueError("Missing transcript metadata")
    document = json.loads(lines[0][len("<!-- transcript: "):-len(" -->")])
    if document.get("schemaVersion") != 1 or document.get("status") not in {"draft", "reviewed"}:
        raise ValueError("Invalid transcript version/status")
    session = next((r for r in catalog["sessions"] if r["id"] == document.get("sessionId")), None)
    source = document.get("source", {})
    if session is None or source.get("bvid") not in {s["id"] for s in session["sources"]}:
        raise ValueError("Transcript source does not belong to this session")
    if type(source.get("page")) is not int or source["page"] < 1:
        raise ValueError("Invalid video page")
    length = source.get("durationSeconds")
    if not isinstance(length, (float, int)) or not math.isfinite(length) or length <= 0:
        raise ValueError("Invalid recording duration")
    if document.get("timing") not in {"chunk", "aligned", "reviewed"}:
        raise ValueError("Invalid timing provenance")
    topics = []
    previous_end = 0
    for number, line in enumerate(lines[1:], 2):
        if not line.strip() or line.startswith("# "):
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            if not title:
                raise ValueError(f"Empty topic at line {number}")
            topics.append({"id": f"topic-{len(topics)+1:03}", "title": title, "segments": []})
            continue
        match = LINE.fullmatch(line)
        if not match or not topics:
            raise ValueError(f"Expected a topic or timed paragraph at line {number}")
        start, end = seconds(match[1]), seconds(match[2])
        if start < previous_end - 0.001 or end <= start or end > length + 1:
            raise ValueError(f"Overlapping, reversed or out-of-range timestamp at line {number}")
        topics[-1]["segments"].append({"start": start, "end": end, "text": match[3]})
        previous_end = end
    if not topics or any(not topic["segments"] for topic in topics):
        raise ValueError("Every topic must contain at least one timed paragraph")
    for topic in topics:
        topic["start"] = topic["segments"][0]["start"]
        topic["end"] = topic["segments"][-1]["end"]
    return {
        "schemaVersion": document["schemaVersion"],
        "sessionId": document["sessionId"],
        "status": document["status"],
        "timing": document["timing"],
        "source": {key: source[key] for key in ("bvid", "page", "durationSeconds")},
        "topics": topics,
    }


def main():
    catalog = json.loads((ROOT / "site/data/catalog.json").read_text())
    compiled = {}
    for path in sorted((ROOT / "content/transcripts").glob("*.md")):
        document = parse_transcript(path.read_text(), catalog)
        session_id = document["sessionId"]
        if path.stem != session_id or session_id in compiled:
            raise ValueError(f"Invalid transcript filename: {path.name}")
        compiled[session_id] = document
    output = ROOT / "site/data/transcripts"
    output.mkdir(parents=True, exist_ok=True)
    for session_id, document in compiled.items():
        temporary = output / f"{session_id}.json.tmp"
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(output / f"{session_id}.json")
    index = {"schemaVersion": 1, "sessions": {key: {"status": doc["status"], "topicCount": len(doc["topics"])} for key, doc in compiled.items()}}
    temporary = output / "index.json.tmp"
    temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output / "index.json")
    print(f"Compiled {len(compiled)} topic transcripts")


if __name__ == "__main__":
    main()
