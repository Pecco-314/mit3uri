const $ = (selector) => document.querySelector(selector);
const PAGE_SIZE = 40;
const state = { catalog: null, transcripts: {}, query: '', period: '', expandedYears: new Set(), sort: 'oldest', page: 1 };
let detailTrigger = null;
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const duration = (seconds) => {
  if (seconds == null) return '—';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return hours ? `${hours}小时${minutes}分` : `${minutes}分`;
};
const dateLabel = (date) => date.replaceAll('-', '.');
const monthLabel = (period) => `${period.slice(0, 4)} 年 ${Number(period.slice(5))} 月`;
const weekday = (date) => ['日', '一', '二', '三', '四', '五', '六'][new Date(`${date}T12:00:00+08:00`).getUTCDay()];
const arrow = '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m7 5 5 5-5 5"/></svg>';

function renderDateNavigation() {
  const years = [...new Set(state.catalog.sessions.map((record) => record.date.slice(0, 4)))].sort();
  $('#date-navigation').innerHTML = '<button class="all-dates" data-period="" aria-pressed="true">全部日期</button>' + years.map((year) => {
    const months = [...new Set(state.catalog.sessions.filter((record) => record.date.startsWith(year)).map((record) => record.date.slice(0, 7)))].sort();
    return `<div class="year-group">
      <button class="year-button" data-year="${year}" aria-expanded="${state.expandedYears.has(year)}" aria-controls="months-${year}">${arrow}<span>${year} 年</span></button>
      <div class="month-list" id="months-${year}" ${state.expandedYears.has(year) ? '' : 'hidden'}>
        ${months.map((month) => `<button data-period="${month}" aria-pressed="false">${Number(month.slice(5))} 月<span>${state.catalog.sessions.filter((record) => record.date.startsWith(month)).length}</span></button>`).join('')}
      </div>
    </div>`;
  }).join('');
  updateNavigation();
}

function updateNavigation() {
  document.querySelectorAll('[data-period]').forEach((button) => {
    const active = button.dataset.period === state.period;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  document.querySelectorAll('[data-year]').forEach((button) => {
    const year = button.dataset.year;
    const expanded = state.expandedYears.has(year);
    button.classList.toggle('active', state.period === year);
    button.setAttribute('aria-pressed', String(state.period === year));
    button.setAttribute('aria-expanded', String(expanded));
    $(`#months-${year}`).hidden = !expanded;
  });
}

function filteredRecords() {
  return state.catalog.sessions.filter((record) => {
    if (state.period && !record.date.startsWith(state.period)) return false;
    const haystack = [record.title, record.date, dateLabel(record.date), ...(record.tags || []), ...record.sources.flatMap((source) => [source.id, source.title, source.uploader])].join(' ').toLocaleLowerCase();
    return !state.query || haystack.includes(state.query.toLocaleLowerCase());
  }).sort((a, b) => {
    const ordering = a.date.localeCompare(b.date) || (a.startedAt || '').localeCompare(b.startedAt || '') || a.id.localeCompare(b.id);
    return state.sort === 'oldest' ? ordering : -ordering;
  });
}

function recordRow(record) {
  const title = escapeHtml(record.title);
  return `<li><button class="replay-row" data-record="${record.id}" aria-label="查看 ${dateLabel(record.date)} ${record.startedAt ? record.startedAt.slice(11, 16) + ' ' : ''}${title} 的详情">
    <time class="row-date" datetime="${record.date}">${record.date.slice(5).replace('-', '.')}<span>周${weekday(record.date)}</span></time>
    <span class="row-title">${title}${(record.tags || []).map(tag => `<span class="session-tag">${escapeHtml(tag)}</span>`).join('')}</span>
    <span class="row-times"><span class="row-start ${record.startedAt ? '' : 'unknown'}" ${record.startedAt ? '' : 'aria-label="开播时间未知"'}>${record.startedAt ? record.startedAt.slice(11, 16) : '—'}</span>
    <span class="row-duration ${(record.liveDurationSeconds ?? record.recordingDurationSeconds) == null ? 'unknown' : ''}" ${(record.liveDurationSeconds ?? record.recordingDurationSeconds) == null ? 'aria-label="时长未知"' : ''}>${duration(record.liveDurationSeconds ?? record.recordingDurationSeconds)}</span></span>
    <span class="row-arrow">${arrow}</span>
  </button></li>`;
}

function render() {
  if (!state.catalog) return;
  const records = filteredRecords();
  const pages = Math.max(1, Math.ceil(records.length / PAGE_SIZE));
  state.page = Math.min(state.page, pages);
  const offset = (state.page - 1) * PAGE_SIZE;
  const groups = new Map();
  for (const record of records.slice(offset, offset + PAGE_SIZE)) {
    const month = record.date.slice(0, 7);
    if (!groups.has(month)) groups.set(month, []);
    groups.get(month).push(record);
  }
  const selection = state.period.length === 7 ? monthLabel(state.period) : state.period ? `${state.period} 年` : '全部日期';
  $('#archive-title').textContent = '录播';
  $('#selection-label').textContent = selection;
  $('#result-count').textContent = `${records.length} 场`;
  $('#recordings').innerHTML = records.length ? [...groups].map(([month, rows]) => `<section class="month-group" aria-labelledby="group-${month}"><h2 id="group-${month}">${monthLabel(month)}</h2><ul class="replay-list">${rows.map(recordRow).join('')}</ul></section>`).join('') : '<div class="empty-state"><p>没有找到相关录播</p><button id="reset-filters">清除筛选</button></div>';
  $('#page-info').textContent = records.length ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, records.length)} / ${records.length} 场` : '0 场';
  $('#page-number').textContent = `${state.page} / ${pages}`;
  $('#previous').disabled = state.page <= 1;
  $('#next').disabled = state.page >= pages;
  updateNavigation();
}

function showRecord(id) {
  id = state.catalog?.sessionAliases?.[id] || id;
  const record = state.catalog?.sessions.find((item) => item.id === id);
  if (!record) return;
  const sources = record.sources.map((source) => `<li class="source-item ${source.official ? 'official' : ''}">
    <div class="source-info"><div class="source-top"><strong>${escapeHtml(source.uploader)}</strong>${source.official ? '<span class="official-label">官方</span>' : ''}${source.segment ? '<span class="segment-label">分段</span>' : ''}</div>
    <p>${escapeHtml(source.title)}</p><div class="source-meta"><span>视频 ${duration(source.durationSeconds)}</span>${source.recordingPages ? `<span>本场 P${source.recordingPages.join('、P')}</span>` : ''}</div></div>
    <a href="${source.url}" target="_blank" rel="noopener noreferrer" aria-label="播放 ${escapeHtml(source.uploader)} 的 ${escapeHtml(source.title)}">播放 ↗</a>
  </li>`).join('');
  $('#detail-content').innerHTML = `<div class="detail-header"><p class="detail-date">${dateLabel(record.date)} · 周${weekday(record.date)}</p><h2 id="detail-title" tabindex="-1">${escapeHtml(record.title)}</h2>
    <dl class="detail-facts"><div><dt>开播时间</dt><dd>${record.startedAt ? record.startedAt.slice(11, 16) : '未知'}</dd></div><div><dt>${record.liveDurationSeconds == null ? '录播时长' : '直播时长'}</dt><dd>${duration(record.liveDurationSeconds ?? record.recordingDurationSeconds)}</dd></div></dl></div>
    <div class="detail-main">${record.summary ? `<section class="summary-section"><h3>摘要</h3><p>${escapeHtml(record.summary)}</p></section>` : ''}<div class="replay-section-heading"><h3>录播链接</h3>${state.transcripts[id] ? `<a class="transcript-entry" href="./transcript.html?id=${encodeURIComponent(id)}"><span>文字稿</span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 14 14 6M6 6h8v8"/></svg></a>` : ''}</div><ul class="source-list">${sources || '<li class="empty-state">暂未找到这场直播的录播。</li>'}</ul></div>`;
  const dialog = $('#detail-dialog');
  if (!dialog.open) {
    detailTrigger = document.activeElement;
    dialog.showModal();
  }
  $('#detail-title').focus({ preventScroll: true });
  dialog.scrollTop = 0;
}

function openFromHash() {
  const id = new URLSearchParams(location.hash.slice(1)).get('replay');
  if (id) showRecord(id);
  else if ($('#detail-dialog').open) $('#detail-dialog').close();
}

function choosePeriod(period) {
  state.period = period;
  state.page = 1;
  render();
}

document.addEventListener('click', (event) => {
  const record = event.target.closest('[data-record]');
  if (record) {
    if (location.hash === `#replay=${record.dataset.record}`) showRecord(record.dataset.record);
    else location.hash = `replay=${record.dataset.record}`;
  }
  const year = event.target.closest('[data-year]');
  if (year) {
    const value = year.dataset.year;
    const collapse = state.period === value && state.expandedYears.has(value);
    state.expandedYears.clear();
    if (!collapse) state.expandedYears.add(value);
    choosePeriod(value);
  }
  const period = event.target.closest('[data-period]');
  if (period) choosePeriod(period.dataset.period);
  if (event.target.closest('[data-close]')) $('#detail-dialog').close();
  if (event.target.closest('#reset-filters')) {
    state.query = '';
    $('#search').value = '';
    choosePeriod('');
    $('#search').focus();
  }
});
$('#search').addEventListener('input', (event) => { state.query = event.target.value.trim(); state.page = 1; render(); });
$('#sort').addEventListener('change', (event) => { state.sort = event.target.value; state.page = 1; render(); });
for (const [id, delta] of [['previous', -1], ['next', 1]]) {
  $('#' + id).addEventListener('click', () => {
    state.page += delta;
    render();
    $('#archive').scrollIntoView({ behavior: 'smooth' });
  });
}
$('#detail-dialog').addEventListener('click', (event) => {
  const dialog = event.currentTarget;
  const box = dialog.getBoundingClientRect();
  if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
});
$('#detail-dialog').addEventListener('close', () => {
  if (location.hash.startsWith('#replay=')) history.replaceState(null, '', location.pathname + location.search);
  if (detailTrigger?.isConnected) detailTrigger.focus({ preventScroll: true });
});
document.addEventListener('keydown', (event) => {
  if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.target.matches('input, textarea, select, [contenteditable="true"]') && !document.querySelector('dialog[open]')) {
    event.preventDefault(); $('#search').focus();
  }
});
window.addEventListener('hashchange', openFromHash);

async function load() {
  try {
    const response = await fetch(new URL('./data/catalog.json', import.meta.url), { cache: 'no-cache' });
    if (!response.ok) throw new Error('Catalog unavailable');
    const catalog = await response.json();
    if (catalog.schemaVersion !== 1 || !Array.isArray(catalog.sessions)) throw new Error('Unsupported catalog');
    state.catalog = catalog;
    try {
      const indexResponse = await fetch(new URL('./data/transcripts/index.json', import.meta.url), { cache: 'no-cache' });
      if (!indexResponse.ok) throw new Error('Transcript index unavailable');
      const index = await indexResponse.json();
      if (index.schemaVersion === 1) state.transcripts = index.sessions;
    } catch (error) { console.warn('Transcript index unavailable', error); }
    const firstYear = catalog.sessions.map((record) => record.date.slice(0, 4)).sort().at(0);
    if (firstYear) state.expandedYears.add(firstYear);
    renderDateNavigation();
    render();
    openFromHash();
  } catch (error) {
    $('#recordings').innerHTML = '<div class="empty-state"><p>加载失败，请重试。</p><button id="retry-load">重新加载</button></div>';
    $('#retry-load').addEventListener('click', load);
    console.error(error);
  }
}
load();
