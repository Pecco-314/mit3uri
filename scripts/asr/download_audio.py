"""Download a public Bilibili audio track and retain its recording time origin."""
import argparse
import json
import time
import urllib.request
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}


def api(path):
    request = urllib.request.Request("https://api.bilibili.com" + path, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    if result.get("code") != 0:
        raise RuntimeError(f"Bilibili: {result.get('code')} {result.get('message')}")
    return result["data"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bvid")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    info = api(f"/x/web-interface/view?bvid={args.bvid}")
    page = next(p for p in info["pages"] if p["page"] == args.page)
    data = api(f"/x/player/playurl?bvid={args.bvid}&cid={page['cid']}&fnval=4048&fnver=0&fourk=1")
    tracks = data.get("dash", {}).get("audio", [])
    if not tracks:
        raise RuntimeError("No public DASH audio track available")
    track = max(tracks, key=lambda t: t.get("bandwidth", 0))
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / f"{args.bvid}-p{args.page}.m4a"
    if not target.exists():
        temporary = target.with_suffix(".part")
        started = time.perf_counter()
        request = urllib.request.Request(track["baseUrl"], headers=HEADERS)
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        temporary.replace(target)
        print(f"Downloaded {target.stat().st_size:,} bytes in {time.perf_counter()-started:.1f}s", flush=True)
    metadata = {
        "bvid": args.bvid, "page": args.page, "cid": page["cid"],
        "title": info["title"], "uploader": info["owner"]["name"],
        "durationSeconds": page["duration"], "bandwidth": track.get("bandwidth"),
        "sourceUrl": f"https://www.bilibili.com/video/{args.bvid}/?p={args.page}",
        "audioFile": target.name, "timeOrigin": "recording",
    }
    target.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metadata, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
