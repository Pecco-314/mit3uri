const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const transcriptText = (value) => escapeHtml(value)
  .replaceAll('\n', '<br><br>')
  .replace(/\bBV[0-9A-Za-z]{10}\b/g, bvid => `<a href="https://www.bilibili.com/video/${bvid}/" target="_blank" rel="noopener noreferrer">${bvid} ↗</a>`);
const time = (seconds) => {
  const value = Math.floor(seconds);
  const hours = Math.floor(value / 3600);
  return `${hours ? `${hours}:` : ''}${String(Math.floor(value % 3600 / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
};
const id = new URLSearchParams(location.search).get('id');
const reader = document.querySelector('#reader');
async function load() {
  reader.innerHTML = '<p class="reader-status" role="status">文字稿加载中…</p>';
  if (!/^MIT3URI-(?:LIVE-)?\d+$/.test(id ?? '')) {
    reader.innerHTML = '<p class="reader-status">未找到这份文字稿。请返回录播列表选择场次。</p>';
    return;
  }
  document.querySelector('#back-link').href = `./#replay=${encodeURIComponent(id)}`;
  try {
    const get = async (path) => {
      const response = await fetch(new URL(path, import.meta.url), { cache: 'no-cache' });
      if (!response.ok) throw new Error('Unavailable');
      return response.json();
    };
    const [catalog, transcript] = await Promise.all([get('./data/catalog.json'), get(`./data/transcripts/${encodeURIComponent(id)}.json`)]);
    const record = catalog.sessions.find((record) => record.id === id);
    if (!record || transcript.schemaVersion !== 1 || transcript.sessionId !== id || !Array.isArray(transcript.topics) || !record.sources.some(source => source.id === transcript.source?.bvid)) throw new Error('Invalid transcript');
    const video = new URL(`https://www.bilibili.com/video/${transcript.source.bvid}/`);
    video.searchParams.set('p', transcript.source.page);
    const play = (start, page = transcript.source.page) => { video.searchParams.set('p', page); video.searchParams.set('t', Math.floor(start)); return escapeHtml(video.href); };
    document.title = `${record.title} · 文字稿`;
    reader.innerHTML = `<div class="reader-layout"><aside class="reader-sidebar"><nav aria-label="话题目录"><p class="toc-heading">话题目录 <span>${transcript.topics.length}</span></p><ol>${transcript.topics.map((topic, i) => `<li><a href="#topic-${i+1}"><time>${time(topic.start + (topic.offset || 0))}</time><span>${escapeHtml(topic.title)}</span></a></li>`).join('')}</ol></nav></aside><article id="transcript-content"><header class="article-header"><p class="reader-date">${escapeHtml(record.date.replaceAll('-', '.'))}${(record.tags || []).map(tag => `<span class="session-tag">${escapeHtml(tag)}</span>`).join('')}</p><h1>${escapeHtml(record.title)}</h1>${record.summary ? `<p class="reader-summary">${escapeHtml(record.summary)}</p>` : ''}<a class="reader-video" href="${play(0)}" target="_blank" rel="noopener noreferrer">观看录播 ↗</a></header>${transcript.topics.map((topic, i) => `<section class="reader-topic" id="topic-${i+1}" aria-labelledby="heading-${i+1}"><h2 id="heading-${i+1}">${escapeHtml(topic.title)}</h2>${topic.segments.map(segment => `<p class="reader-paragraph"><a class="reader-time" href="${play(segment.start, segment.page ?? topic.page)}" target="_blank" rel="noopener noreferrer" aria-label="从 ${time(segment.start + (segment.offset ?? topic.offset ?? 0))} 播放录播">${time(segment.start + (segment.offset ?? topic.offset ?? 0))} ↗</a><span>${transcriptText(segment.text)}</span></p>`).join('')}</section>`).join('')}<a class="reader-top" href="#reader">返回顶部 ↑</a></article></div>`;
    if (/^#topic-\d+$/.test(location.hash)) document.querySelector(location.hash)?.scrollIntoView();
    const links = [...reader.querySelectorAll('.reader-sidebar a')];
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (!visible.length) return;
      links.forEach(link => {
        if (link.hash === `#${visible[0].target.id}`) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
    }, { rootMargin: '-8% 0px -65% 0px' });
    reader.querySelectorAll('.reader-topic').forEach(section => observer.observe(section));
  } catch (error) {
    reader.innerHTML = '<div class="reader-status"><p role="status">文字稿暂时无法加载。</p><button id="retry-reader">重新加载</button></div>';
    document.querySelector('#retry-reader').addEventListener('click', load);
  }
}
load();
