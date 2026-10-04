"""Fetch static model weights from ModelScope and verify each file's SHA-256."""
import argparse
import concurrent.futures
import hashlib
import json
import urllib.request
from pathlib import Path
from urllib.parse import quote


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="mlx-community/Qwen3-ASR-1.7B-8bit")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    api = f"https://modelscope.cn/api/v1/models/{args.model}/repo/files?Recursive=true"
    with urllib.request.urlopen(api, timeout=60) as response:
        manifest = json.load(response)
    if manifest.get("Code") != 200:
        raise RuntimeError("Model metadata unavailable")
    args.output.mkdir(parents=True, exist_ok=True)
    files = [f for f in manifest["Data"]["Files"] if f["Type"] == "blob" and not f["Path"].startswith('.')]

    def download(item):
        path = args.output / item["Path"]
        if not path.resolve().is_relative_to(args.output.resolve()):
            raise ValueError("Invalid model filename")
        expected = item["Sha256"]
        if path.exists() and hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() == expected:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.part')
        url = f"https://modelscope.cn/models/{args.model}/resolve/{quote(item['Revision'], safe='')}/{quote(item['Path'])}"
        digest = hashlib.sha256()
        print(f"Downloading {item['Path']} ({item['Size']/1024**2:.1f} MiB)", flush=True)
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
            while block := response.read(4 * 1024 * 1024):
                output.write(block)
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"Checksum mismatch: {item['Path']}")
        temporary.replace(path)
        print(f"Verified {item['Path']}", flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, files))
    (args.output / 'download-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
