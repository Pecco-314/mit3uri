import { cp, mkdir, readFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const root = new URL('../', import.meta.url);
const catalog = JSON.parse(await readFile(new URL('site/data/catalog.json', root), 'utf8'));
if (catalog.schemaVersion !== 1 || !catalog.sessions.length) throw new Error('Missing catalog');
const ids = new Set();
const bvids = new Set();
const partsByVideo = new Map();
const timeEvidenceKinds = new Set(['bilibili_live_event', 'vtbcat_start_at', 'live_history', 'danmakus_history', 'audited_recording_timestamp', 'qingli_recording_title', 'verified_replay_clock', 'aligned_recording_part']);
for (const record of catalog.sessions) {
  if (ids.has(record.id)) throw new Error(`Duplicate session: ${record.id}`);
  ids.add(record.id);
  if (record.startedAt && !timeEvidenceKinds.has(record.timeEvidence)) throw new Error(`Unverified start: ${record.id}`);
  if (record.liveDurationSeconds != null && (!record.startedAt || record.liveDurationSeconds <= 0)) throw new Error(`Invalid duration: ${record.id}`);
  if (record.recordingDurationSeconds != null && (!record.sources.length || record.recordingDurationSeconds <= 0)) throw new Error(`Invalid recording length: ${record.id}`);
  let communitySeen = false;
  for (const source of record.sources) {
    const parts = source.recordingPages;
    if (parts && (!parts.length || parts.some(p => !Number.isInteger(p) || p < 1) || new Set(parts).size !== parts.length)) throw new Error(`Invalid parts: ${source.id}`);
    if (bvids.has(source.id)) {
      const prior = partsByVideo.get(source.id);
      if (!parts || !prior || parts.some(p => prior.has(p))) throw new Error(`Overlapping recording: ${source.id}`);
      parts.forEach(p => prior.add(p));
    } else partsByVideo.set(source.id, parts ? new Set(parts) : null);
    bvids.add(source.id);
    const expectedUrl = `https://www.bilibili.com/video/${source.id}/${parts ? `?p=${parts[0]}` : ''}`;
    if (!/^BV[A-Za-z0-9]{10}$/.test(source.id) || source.url !== expectedUrl) throw new Error('Invalid video URL');
    if (source.official !== (source.uploaderId === catalog.channel.uid)) throw new Error('Incorrect official source');
    if (source.official && communitySeen) throw new Error('Official source must come first');
    if (!source.official) communitySeen = true;
  }
}
for (const [oldId, target] of Object.entries(catalog.sessionAliases || {})) {
  if (ids.has(oldId) || !ids.has(target)) throw new Error(`Invalid session alias: ${oldId}`);
}
const output = new URL('dist/', root);
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await cp(new URL('site/', root), output, { recursive: true });
console.log(`Static site: ${fileURLToPath(output)} (${ids.size} sessions, ${bvids.size} links)`);
