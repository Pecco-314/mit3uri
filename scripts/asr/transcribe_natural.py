"""Local pause-aware Qwen ASR, separate song routing, and sentence alignment."""
import argparse
import gc
import hashlib
import importlib.metadata
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from natural_segments import merge_reviewed_regions, plan_regions, sentence_spans
from audio_utils import ROOT, decode, review_flags, stamp


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--regions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reuse', type=Path, help='Completed pipeline.json with identical audio and inference settings')
    args = parser.parse_args()
    import mlx.core as mx
    from mlx_audio.stt import load
    from mlx_audio.vad import load as load_vad
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    audio = decode(args.audio)
    with args.audio.open('rb') as source:
        audio_hash = hashlib.file_digest(source, 'sha256').hexdigest()
    config = json.loads(args.regions.read_text())
    if config['sessionId'] != args.session:
        raise ValueError('Region/session mismatch')
    vocabulary = json.loads((ROOT / 'content/vocabulary.json').read_text())
    words = list(dict.fromkeys(vocabulary['global'] + vocabulary.get('sessions', {}).get(args.session, [])))
    settings = {'pipelineVersion': 1, 'audioSha256': audio_hash, 'hotwords': words,
                'model': str(ROOT / '.cache/asr/models/Qwen3-ASR-1.7B-8bit'),
                'vadModel': str(ROOT / '.cache/asr/models/silero-vad'),
                'alignerModel': str(ROOT / '.cache/asr/models/Qwen3-ForcedAligner-0.6B-bf16'),
                'engineVersion': importlib.metadata.version('mlx-audio'),
                'temperature': 0, 'seed': 17, 'maxTokens': 3072,
                'minSeconds': 18, 'maxSeconds': 90, 'pauseSeconds': 0.8,
                'vad': {'threshold': 0.5, 'min_speech_duration_ms': 200,
                        'min_silence_duration_ms': 300, 'speech_pad_ms': 0},
                'regions': config, 'songHotwords': [], 'segmentation': 'vad-pause-with-song-regions'}
    state_path = args.output / 'pipeline.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['settings'] != settings:
            raise ValueError('Settings changed; use a new output directory')
        if state.get('complete'):
            print('Already complete:', state_path)
            return
    else:
        state = {'settings': settings, 'sessionId': args.session, 'schemaVersion': 1,
                 'audioDurationSeconds': len(audio)/16000,
                 'source': json.loads(args.audio.with_suffix('.json').read_text()),
                 'complete': False, 'segments': [], 'alignments': {}}
    reuse = None
    if args.reuse:
        reuse = json.loads(args.reuse.read_text())
        if not reuse.get('complete') or any(reuse['settings'].get(k) != v for k, v in settings.items() if k != 'regions'):
            raise ValueError('Reusable result has incompatible inference settings')
        if 'plan' not in state:
            state['vad'] = reuse['vad']
            state['vadSeconds'] = 0
            state['reusedFrom'] = str(args.reuse.resolve())
            state['plan'] = merge_reviewed_regions(plan_regions(len(audio)/16000, state['vad'], config['songs'],
                settings['minSeconds'], settings['maxSeconds'], settings['pauseSeconds']), config.get('mergeGroups', []))
            save(state_path, state)
    if 'plan' not in state:
        before = time.perf_counter()
        vad = load_vad(settings['vadModel'])
        speech = vad.get_speech_timestamps(audio, sample_rate=16000, return_seconds=True, **settings['vad'])
        state['vad'] = speech
        state['vadSeconds'] = time.perf_counter() - before
        state['plan'] = plan_regions(len(audio)/16000, speech, config['songs'],
                                     settings['minSeconds'], settings['maxSeconds'], settings['pauseSeconds'])
        state['plan'] = merge_reviewed_regions(state['plan'], config.get('mergeGroups', []))
        del vad
        gc.collect()
        mx.clear_cache()
        save(state_path, state)
    print('Plan:', len(state['plan']), 'regions;', len(state['vad']), 'VAD intervals', flush=True)
    if len(state['segments']) < len(state['plan']):
        model = load(settings['model'])
        for i, region in enumerate(state['plan']):
            if i < len(state['segments']):
                continue
            previous = next((s for s in reuse['segments'] if all(s.get(k) == region.get(k)
                for k in ('id', 'start', 'end', 'kind', 'language'))) , None) if reuse else None
            if previous:
                state['segments'].append(dict(previous, reusedFrom=str(args.reuse.resolve())))
                state['alignments'][region['id']] = reuse['alignments'][region['id']]
                save(state_path, state)
                continue
            before = time.perf_counter()
            mx.random.seed(settings['seed'] + i)
            output = model.generate(audio[round(region['start']*16000):round(region['end']*16000)],
                                    max_tokens=settings['maxTokens'], temperature=0,
                                    language=None if region['language'] == 'auto' else region['language'],
                                    hotwords=[] if region['kind'] == 'song' else words, verbose=False)
            text = output.text.strip()
            flags = list(region.get('needsReview', []))
            flags += review_flags(text, words, output.generation_tokens, settings['maxTokens'])
            if not text:
                flags.append('empty_asr')
            if region['kind'] == 'song':
                flags.append('singing_unverified')
            s = dict(region, text=text, needsReview=flags, generationTokens=output.generation_tokens,
                     wallSeconds=round(time.perf_counter()-before, 3))
            state['segments'].append(s)
            save(state_path, state)
            print(f"ASR {i+1}/{len(state['plan'])} {stamp(s['start'])}–{stamp(s['end'])}: {text[:95]}", flush=True)
            mx.clear_cache()
        del model
        gc.collect()
        mx.clear_cache()
    raw = {k: v for k, v in state.items() if k not in ('alignments', 'plan', 'vad')}
    raw.update(complete=True, timing='vad-region', transcribeSeconds=sum(s['wallSeconds'] for s in state['segments']))
    save(args.output / 'raw.json', raw)
    (args.output / 'raw.txt').write_text('\n'.join(f"[{stamp(s['start'])} --> {stamp(s['end'])}] {s['text']}" for s in state['segments']))
    aligner = load(settings['alignerModel'])
    for i, segment in enumerate(state['segments']):
        if segment['id'] in state['alignments']:
            continue
        before = time.perf_counter()
        entry = {'sentences': [], 'items': [], 'status': 'skipped'}
        if segment['text'] and 'token_limit' not in segment['needsReview'] and 'suspected_hotword_echo' not in segment['needsReview']:
            try:
                result = aligner.generate(audio[round(segment['start']*16000):round(segment['end']*16000)],
                                          text=segment['text'], language='Chinese' if segment['language'] == 'auto' else segment['language'])
                entry['items'] = result.segments
                entry['sentences'] = sentence_spans(segment['text'], result.segments,
                                                     segment['start'], segment['end']-segment['start'])
                entry['status'] = 'aligned'
            except (ValueError, ImportError) as error:
                entry['status'], entry['error'] = 'needs_review', str(error)
        entry['wallSeconds'] = round(time.perf_counter()-before, 3)
        state['alignments'][segment['id']] = entry
        save(state_path, state)
        print(f"Align {i+1}/{len(state['segments'])}: {entry['status']} {len(entry['sentences'])} sentences {entry.get('error', '')}", flush=True)
        mx.clear_cache()
    state['complete'] = True
    state['generatedAt'] = datetime.now(timezone.utc).isoformat()
    state['lastInvocationWallSeconds'] = round(time.perf_counter()-started, 3)
    state['peakMemoryBytes'] = mx.get_peak_memory()
    save(state_path, state)
    print('Complete:', state_path, state['lastInvocationWallSeconds'], 'seconds', flush=True)


if __name__ == '__main__':
    main()
