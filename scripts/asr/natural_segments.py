"""Pause-based audio planning and punctuation-preserving sentence alignment."""
import math
import re


def plan_regions(duration, speech, songs, min_seconds=18, max_seconds=90, pause_seconds=0.8):
    """Cover all audio once; prefer VAD pauses and retain non-speech for ASR review."""
    if not 0 < min_seconds < max_seconds or duration <= 0:
        raise ValueError('Invalid duration limits')
    previous = 0
    for song in songs:
        if not all(math.isfinite(song[k]) for k in ('start', 'end')) or not previous <= song['start'] < song['end'] <= duration:
            raise ValueError('Song ranges must be finite, ordered and disjoint')
        if song['end'] - song['start'] > 300:
            raise ValueError('Songs longer than five minutes require explicit phrase boundaries')
        previous = song['end']
    pauses = []
    for a, b in zip(speech, speech[1:]):
        gap = b['start'] - a['end']
        if gap >= 0.3:
            pauses.append(((a['end'] + b['start']) / 2, gap))
    # Separate long lead-in/outro silence while preserving it for recognition.
    if speech and speech[0]['start'] > 2:
        pauses.append((max(0, speech[0]['start'] - 0.3), speech[0]['start']))
    if speech and duration - speech[-1]['end'] > 2:
        pauses.append((min(duration, speech[-1]['end'] + 0.3), duration - speech[-1]['end']))
    pauses.sort()
    result = []

    def talk(start, end):
        while start < end - 1e-5:
            limit = min(end, start + max_seconds)
            candidates = [(p, gap) for p, gap in pauses if start + min_seconds <= p <= limit]
            strong = [p for p, gap in candidates if gap >= pause_seconds]
            if strong:
                cut, reason = strong[0], 'vad_pause'
            elif end - start <= max_seconds:
                cut, reason = end, 'region_end'
            elif candidates:
                cut, reason = candidates[-1][0], 'vad_short_pause'
            else:
                cut, reason = limit, 'duration_fallback'
            voiced = sum(max(0, min(cut, s['end']) - max(start, s['start'])) for s in speech)
            result.append({'id': f'talk-{len(result)+1:03}', 'start': start, 'end': cut,
                           'kind': 'speech', 'language': 'auto', 'boundary': reason,
                           'vadSpeechSeconds': round(voiced, 3),
                           'needsReview': (['duration_fallback'] if reason == 'duration_fallback' else []) +
                                          (['low_vad_activity'] if voiced < 0.5 else [])})
            start = cut

    start = 0
    for song in songs:
        talk(start, song['start'])
        result.append(dict(song, kind='song', boundary='draft_song_range'))
        start = song['end']
    talk(start, duration)
    return result


def normalized(text):
    return ''.join(c.casefold() for c in text if c.isalnum())


def merge_reviewed_regions(plan, groups):
    """Re-recognize adjacent speech regions whose text suggests a broken sentence."""
    result = [dict(s) for s in plan]
    for group in groups:
        ids = group['ids']
        indices = [i for i, s in enumerate(result) if s['id'] in ids]
        if not ids or len(indices) != len(ids) or indices != list(range(indices[0], indices[-1]+1)):
            raise ValueError('Merge groups must contain existing adjacent regions')
        chosen = [result[i] for i in indices]
        if any(s['kind'] != 'speech' for s in chosen) or chosen[-1]['end']-chosen[0]['start'] > 300:
            raise ValueError('Only speech regions up to five minutes can be merged')
        merged = dict(chosen[0], id='+'.join(s['id'] for s in chosen), end=chosen[-1]['end'],
                      boundary='text_review_merge', mergedFrom=ids, mergeReason=group['reason'],
                      needsReview=['reviewed_seam_unverified_audio'])
        result[indices[0]:indices[-1]+1] = [merged]
    return result


def sentence_spans(text, items, offset, duration):
    """Map punctuation-delimited original text to aligned units, without rewording."""
    if normalized(text) != ''.join(normalized(i['text']) for i in items):
        raise ValueError('Alignment token text does not match original transcript')
    if not items:
        return []
    for i, item in enumerate(items):
        if not (math.isfinite(item['start']) and math.isfinite(item['end']) and
                0 <= item['start'] <= item['end'] <= duration + 0.08):
            raise ValueError('Alignment timestamp outside source region')
        if i and item['start'] < items[i-1]['end'] - 0.02:
            raise ValueError('Alignment timestamps overlap or reverse')
    char_items = [i for i, item in enumerate(items) for _ in normalized(item['text'])]
    spans, cursor = [], 0
    for match in re.finditer(r'.+?(?:[。！？!?]+[”」』"]*|$)', text, re.S):
        sentence = match.group()
        n = len(normalized(sentence))
        if not n:
            if spans:
                spans[-1]['text'] += sentence
            continue
        first, last = items[char_items[cursor]], items[char_items[cursor+n-1]]
        flags = []
        start, end = first['start'] + offset, min(last['end'], duration) + offset
        if end <= start or any(i['end'] == i['start'] for i in items[char_items[cursor]:char_items[cursor+n-1]+1]):
            flags.append('alignment_zero_duration')
        spans.append({'start': round(start, 3), 'end': round(end, 3), 'text': sentence,
                      'needsReview': flags, 'timing': 'forced_alignment'})
        cursor += n
    if ''.join(s['text'] for s in spans) != text:
        raise ValueError('Sentence splitting did not preserve source text')
    return spans
