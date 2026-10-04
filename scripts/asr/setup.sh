#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
ASR_PYTHON="${ASR_PYTHON:-python3.12}"
"$ASR_PYTHON" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
"$ASR_PYTHON" -m venv .venv-asr
.venv-asr/bin/python -m pip install --disable-pip-version-check -r scripts/asr/requirements-macos.lock
