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


def speech_timestamps(vad, audio, *, sample_rate=16000, batch_seconds=300,
                      clear_cache=lambda: None, **options):
    """Bound VAD inference memory while retaining one continuous audio timeline."""
    size = int(sample_rate * batch_seconds)
    if size <= 0:
        raise ValueError('VAD batch length must be positive')
    speech = []
    for start in range(0, len(audio), size):
        rows = vad.get_speech_timestamps(audio[start:start + size], sample_rate=sample_rate,
                                        return_seconds=True, **options)
        offset = start / sample_rate
        for row in rows:
            interval = {'start': offset + row['start'], 'end': offset + row['end']}
            if speech and interval['start'] <= speech[-1]['end'] + 0.05:
                speech[-1]['end'] = max(speech[-1]['end'], interval['end'])
            else:
                speech.append(interval)
        clear_cache()
    return speech
