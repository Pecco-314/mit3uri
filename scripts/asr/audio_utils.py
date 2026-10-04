"""Audio decoding, timestamps and output checks for local transcription."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def review_flags(text, words, token_count, limit):
    flags = []
    if token_count >= limit:
        flags.append('token_limit')
    normalized = re.sub(r'[^\w]', '', text).casefold()
    vocabulary = [re.sub(r'[^\w]', '', word).casefold() for word in words]
    matched = [word for word in vocabulary if word and word in normalized]
    remainder = normalized
    for word in sorted(matched, key=len, reverse=True):
        remainder = remainder.replace(word, '')
    if len(matched) >= 3 and not remainder:
        flags.append('suspected_hotword_echo')
    return flags


def decode(path):
    import av
    import numpy as np
    samples = []
    resampler = av.AudioResampler(format='fltp', layout='mono', rate=16000)
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            samples.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(frame))
    samples.extend(f.to_ndarray().reshape(-1) for f in resampler.resample(None))
    return np.concatenate(samples).astype(np.float32)


def stamp(seconds):
    milliseconds = round(seconds * 1000)
    minutes, remainder = divmod(milliseconds, 60000)
    return f"{minutes:02}:{remainder//1000:02}.{remainder%1000:03}"
