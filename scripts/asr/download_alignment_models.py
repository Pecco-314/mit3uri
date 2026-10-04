"""Download pinned MLX VAD/alignment weights and record local SHA-256 manifests."""
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download

from audio_utils import ROOT

MODELS = {
    'silero-vad': '7bc17f22d3c0451bd3a6cd71e759b009271ff49a',
    'Qwen3-ForcedAligner-0.6B-bf16': '53c8c0e46733eec430e4b53dd6471d0e5dee45f8',
}


def main():
    for name, revision in MODELS.items():
        directory = ROOT / '.cache/asr/models' / name
        snapshot_download('mlx-community/' + name, revision=revision, local_dir=directory)
        files = {}
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.name != 'download-manifest.json':
                with path.open('rb') as stream:
                    files[path.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        (directory / 'download-manifest.json').write_text(json.dumps({
            'repository': 'mlx-community/' + name, 'revision': revision, 'sha256': files,
        }, indent=2) + '\n')
        print(directory)


if __name__ == '__main__':
    main()
