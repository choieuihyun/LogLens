/* LogLens web UI — 의존성 없는 바닐라 JS.
 *
 * 서버는 SSE 로 파싱된 레코드를 밀어준다. 브라우저는 필터링/렌더/집계표시만 한다.
 * 렌더는 100ms 스로틀 + 최대 표시 줄 수 상한으로 억제한다 (로그는 초당 수백 줄이 온다).
 */
'use strict';

const MAX_BUFFER = 20000;   // 클라이언트 링버퍼
const MAX_RENDER = 1500;    // 실제로 DOM 에 그리는 최근 줄 수
const LEVELS = ['V', 'D', 'I', 'W', 'E'];
const RANK = { V: 0, D: 1, I: 2, W: 3, E: 4 };

const $ = (id) => document.getElementById(id);

const state = {
  cfg: null,
  records: [],
  issues: [],
  tab: 'all',
  levels: new Set(['D', 'I', 'W', 'E']),
  q: '',
  rx: false,
  rxCompiled: null,
  onlyStruct: false,
  onlyPid: false,
  pid: null,              // 지금 돌고 있는 대상 앱 pid
  pids: [],               // 이번 세션에서 본 대상 앱 pid 전부 (앱 재시작 대비)
  paused: false,
  autoscroll: true,
  issueFilter: null,      // {ruleId, key}
  collapsed: new Set(),   // 접어 둔 노드 id
  treeData: null,
  dirty: true,
};

/* ── 부팅 ──────────────────────────────────────────── */
async function boot() {
  state.cfg = await (await fetch('/api/config')).json();
  $('src').textContent = describeSource(state.cfg.source);
  applyPid(state.cfg.source);
  buildTabs();
  buildLevels();
  wire();

  const snap = await (await fetch('/api/snapshot?limit=3000')).json();
  state.records = snap.records;
  state.issues = snap.issues;
  setStatus(snap.status, true);
  state.dirty = true;

  connect();
  setInterval(render, 100);
  setInterval(pollIssues, 1500);
  refreshTree();
  setInterval(refreshTree, 2500);
}

/* 대상 앱 pid 필터. pid 를 아는 소스(adb + --package)에서만 노출한다. */
function applyPid(src) {
  state.pid = (src && src.pid) || null;
  // 앱이 재시작되면 pid 가 바뀌는데, 재시작 전 로그도 같은 앱의 로그다.
  // 세션 동안 본 pid 를 전부 받아서 같이 통과시킨다.
  state.pids = (src && src.pids && src.pids.length) ? src.pids
             : (state.pid ? [state.pid] : []);
  const wrap = $('pidWrap');
  wrap.hidden = !state.pids.length;
  if (state.pids.length) {
    const extra = state.pids.length > 1 ? ` +${state.pids.length - 1}` : '';
    $('pidLabel').textContent = `${src.package || '이 앱'}만 (pid ${state.pid}${extra})`;
  } else if (state.onlyPid) {
    // 앱이 재시작돼 pid 를 잃으면 필터를 끈다. 안 그러면 화면이 통째로 빈다.
    state.onlyPid = false;
    $('onlyPid').checked = false;
  }
}

function describeSource(s) {
  if (!s) return '';
  if (s.kind === 'adb') return `adb · ${s.serial || 'default'}${s.package ? ' · ' + s.package : ''}`;
  if (s.kind === 'file') return `file · ${s.path}`;
  return `synth · ${s.rate}/s`;
}

/* ── SSE 연결 (자동 재연결) ─────────────────────────── */
function connect() {
  const es = new EventSource('/api/stream');
  es.addEventListener('open', () => setStatus('스트리밍 중', true));
  es.addEventListener('logs', (e) => {
    if (state.paused) return;
    const batch = JSON.parse(e.data);
    for (const r of batch) {
      state.records.push(r);
      if (r.raw && r.raw.startsWith('--------- loglens:')) {
        setStatus(r.raw.replace('--------- loglens:', '').trim(), true);
      }
    }
    if (state.records.length > MAX_BUFFER) {
      state.records.splice(0, state.records.length - MAX_BUFFER);
    }
    state.dirty = true;
  });
  es.addEventListener('error', () => {
    // EventSource 는 스스로 재연결한다. 상태만 반영.
    setStatus('연결 끊김 — 재연결 중', false);
  });
}

function setStatus(text, ok) {
  $('status').textContent = text || '';
  $('dot').className = 'dot ' + (ok ? 'on' : 'off');
}

/* ── 탭 / 레벨 ─────────────────────────────────────── */
function buildTabs() {
  const tabs = [{ id: 'all', label: '전체' }]
    .concat(state.cfg.tabs || [])
    .concat([{ id: '__other', label: '미분류' }]);
  const el = $('tabs');
  el.innerHTML = '';
  for (const t of tabs) {
    const d = document.createElement('div');
    d.className = 'tab' + (t.id === state.tab ? ' on' : '');
    d.dataset.id = t.id;
    d.innerHTML = `${esc(t.label)}<span class="n" data-n="${esc(t.id)}">0</span>`;
    d.onclick = () => { state.tab = t.id; buildTabs(); state.dirty = true; };
    el.appendChild(d);
  }
}

function buildLevels() {
  const el = $('levels');
  el.innerHTML = '';
  for (const l of LEVELS) {
    const d = document.createElement('div');
    d.className = 'lv' + (state.levels.has(l) ? ' on' : '');
    d.dataset.l = l;
    d.textContent = l;
    d.onclick = () => {
      state.levels.has(l) ? state.levels.delete(l) : state.levels.add(l);
      buildLevels(); state.dirty = true;
    };
    el.appendChild(d);
  }
}

function wire() {
  $('q').oninput = (e) => {
    state.q = e.target.value;
    compileQuery();
    state.dirty = true;
  };
  $('rx').onchange = (e) => { state.rx = e.target.checked; compileQuery(); state.dirty = true; };
  $('onlyStruct').onchange = (e) => { state.onlyStruct = e.target.checked; state.dirty = true; };
  $('onlyPid').onchange = (e) => { state.onlyPid = e.target.checked; state.dirty = true; };
  $('autoscroll').onchange = (e) => { state.autoscroll = e.target.checked; };
  $('btnPause').onclick = () => {
    state.paused = !state.paused;
    $('btnPause').textContent = state.paused ? '재개' : '일시정지';
    $('btnPause').classList.toggle('active', state.paused);
  };
  $('btnClear').onclick = async () => {
    await fetch('/api/clear', { method: 'POST' });
    state.records = []; state.issues = []; state.issueFilter = null;
    state.dirty = true;
  };
  $('btnDash').onclick = openDash;
  $('dashClose').onclick = () => { $('dash').hidden = true; };
  // 사용자가 위로 스크롤하면 자동스크롤을 끈다 (읽는 중에 끌려가지 않게)
  $('logs').addEventListener('scroll', () => {
    const el = $('logs');
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (!atBottom && state.autoscroll) { state.autoscroll = false; $('autoscroll').checked = false; }
  });
}

function compileQuery() {
  $('q').classList.remove('bad');
  state.rxCompiled = null;
  if (state.rx && state.q) {
    try { state.rxCompiled = new RegExp(state.q, 'i'); }
    catch (_) { $('q').classList.add('bad'); }
  }
}

/* ── 필터 ──────────────────────────────────────────── */
function tabOf(id) {
  return (state.cfg.tabs || []).find((t) => t.id === id);
}

function inTab(r, id) {
  if (id === 'all') return true;
  if (id === '__other') {
    // 어떤 탭에도 안 잡히는 것들
    return !(state.cfg.tabs || []).some((t) => matchTab(r, t));
  }
  const t = tabOf(id);
  return t ? matchTab(r, t) : true;
}

function matchTab(r, t) {
  if (r.domain && (t.domains || []).includes(r.domain)) return true;
  if (t.legacyTagPattern && r.tag) {
    try { if (new RegExp(t.legacyTagPattern).test(r.tag)) return true; } catch (_) {}
  }
  return false;
}

function textOf(r) {
  if (r._t !== undefined) return r._t;
  const parts = [r.tag || '', r.event || '', r.msg || '', r.raw || ''];
  for (const k in r.fields) parts.push(k + '=' + r.fields[k]);
  r._t = parts.join(' ');
  return r._t;
}

function passes(r) {
  if (!state.levels.has(r.level)) return false;
  if (state.onlyStruct && r.kind !== 'structured') return false;
  if (!inTab(r, state.tab)) return false;
  if (state.issueFilter && !matchIssue(r)) return false;
  // 이슈를 찍어서 들어온 상태에서는 pid 필터를 적용하지 않는다.
  // ANR 은 system_server(ActivityManager) 가 찍으므로 앱 pid 로 거르면
  // 방금 클릭한 이슈가 화면에서 사라진다.
  if (!state.issueFilter && state.onlyPid && state.pids.length
      && !state.pids.includes(r.pid)) return false;
  if (state.q) {
    const hay = textOf(r);
    if (state.rxCompiled) { if (!state.rxCompiled.test(hay)) return false; }
    else if (state.rx) { /* 잘못된 정규식 — 필터 미적용 */ }
    else if (!hay.toLowerCase().includes(state.q.toLowerCase())) return false;
  }
  return true;
}

function matchIssue(r) {
  const f = state.issueFilter;
  if (f.ruleId === 'structured_error') {
    return r.kind === 'structured' && `${r.domain}/${r.event}` === f.key;
  }
  return (r.raw || '').includes(f.key);
}

/* ── 렌더 ──────────────────────────────────────────── */
function render() {
  if (!state.dirty) return;
  state.dirty = false;

  const counts = { all: state.records.length, __other: 0 };
  for (const t of state.cfg.tabs || []) counts[t.id] = 0;

  const shown = [];
  for (const r of state.records) {
    for (const t of state.cfg.tabs || []) if (matchTab(r, t)) counts[t.id]++;
    if (!(state.cfg.tabs || []).some((t) => matchTab(r, t))) counts.__other++;
    if (passes(r)) shown.push(r);
  }

  for (const el of document.querySelectorAll('.tab .n')) {
    el.textContent = counts[el.dataset.n] ?? 0;
  }
  $('cShown').textContent = shown.length;
  $('cTotal').textContent = state.records.length;

  // 계층 규칙이 붙은 탭이면 트리를 로그 **옆에** 같이 띄운다. 둘 중 하나를 고르는 게 아니다.
  const tree = treeOfTab(state.tab);
  $('treePane').hidden = !tree;
  if (tree) renderTree(tree);

  const slice = shown.slice(-MAX_RENDER);
  const logs = $('logs');
  logs.innerHTML = slice.map(rowHtml).join('');
  if (state.autoscroll) logs.scrollTop = logs.scrollHeight;
}

/* ── 계층 트리 ─────────────────────────────────────── */
/* 별도 화면이 아니라 도메인 탭 안에서 본다. '전체' 탭은 로그가 너무 많아 제외.
   뷰어는 언제나 부분 트리만 본다 — 사용자가 펼친 것만 로그가 남으니까. */

function treeOfTab(tabId) {
  if (tabId === 'all' || tabId === '__other') return null;
  const tab = tabOf(tabId);
  if (!tab) return null;
  return (state.cfg.trees || []).find((x) => (tab.domains || []).includes(x.domain)) || null;
}

async function refreshTree() {
  try {
    const all = await (await fetch('/api/tree')).json();
    state.treeData = {};
    for (const t of all) state.treeData[t.id] = t;
    if (treeOfTab(state.tab)) state.dirty = true;
  } catch (_) {}
}

function renderTree(cfgTree) {
  const t = state.treeData && state.treeData[cfgTree.id];
  const el = $('treePane');
  const keepScroll = el.scrollTop;
  if (!t) { el.innerHTML = '<p class="empty">세우는 중…</p>'; return; }
  if (!t.nodeCount) {
    el.innerHTML = '<p class="empty">아직 계층 로그가 없습니다. 앱에서 해당 화면을 펼쳐 보세요.</p>';
    return;
  }
  const sum = `<div class="tsum">
    <span>노드 <b>${t.nodeCount}</b></span>
    <span>뿌리 <b>${t.rootCount}</b></span>
    <span>최대 깊이 <b>${t.maxDepth}</b></span>
    ${t.missingTotal ? `<span class="warn">안 펼친 자식 <b>${t.missingTotal}</b></span>` : ''}
    ${t.orphanCount ? `<span class="warn">부모 못 찾음 <b>${t.orphanCount}</b></span>` : ''}
    ${t.depthMismatch ? `<span class="warn" title="parent 로 세운 깊이가 앱이 적어 준 depth 와 다릅니다. parent 필드를 확인하세요.">깊이 불일치 <b>${t.depthMismatch}</b></span>` : ''}
  </div>`;
  el.innerHTML = sum + t.roots.map(nodeHtml).join('');
  el.scrollTop = keepScroll;      // 주기적 갱신 때 읽던 자리를 잃지 않게

  // 줄 아무 데나 누르면 그 자리에서 펼쳐지고 접힌다. 파일 탐색기와 같은 동작이다.
  for (const n of el.querySelectorAll('.tnode')) {
    n.onclick = () => {
      const id = n.dataset.id;
      state.collapsed.has(id) ? state.collapsed.delete(id) : state.collapsed.add(id);
      state.dirty = true;
    };
  }
}

function nodeHtml(n) {
  const kids = n.children || [];
  const isCollapsed = state.collapsed.has(n.id);
  const caret = kids.length
    ? `<span class="caret">${isCollapsed ? '▸' : '▾'}</span>`
    : '<span class="caret leaf">·</span>';
  const metrics = Object.entries(n.metrics || {})
    .map(([k, v]) => `<span class="tw-m">${esc(k)}=${esc(v)}</span>`).join(' ');
  const more = n.missing ? `<span class="tw-more">+${n.missing} 안 펼침</span>` : '';
  const bad = n.depthMismatch
    ? `<span class="tw-more" style="color:var(--e);background:rgba(248,113,113,.12)">깊이 ${n.depth}≠${n.loggedDepth}</span>` : '';
  const sub = kids.length
    ? `<div class="tkids${isCollapsed ? ' hidden' : ''}">${kids.map(nodeHtml).join('')}</div>` : '';
  return `<div class="tnode${n.orphan ? ' orphan' : ''}" data-id="${esc(n.id)}"
      title="${n.orphan ? '부모 줄을 아직 못 봤습니다' : ''}">
      ${caret}<span class="tw-id">${esc(n.id)}</span>
      ${n.name ? `<span class="tw-name">${esc(n.name)}</span>` : ''}
      ${metrics}${more}${bad}
      ${n.hits > 1 ? `<span class="tw-hits">×${n.hits}</span>` : ''}
    </div>${sub}`;
}

function rowHtml(r) {
  const cls = `row lv-${r.level}` + (r.kind === 'raw' ? ' raw' : '');
  const ts = r.ts ? `<span class="ts">${esc(shortTs(r.ts))}</span>` : '';
  const lvl = `<span class="lvl">${r.level}</span>`;

  if (r.kind === 'structured') {
    const fields = Object.entries(r.fields || {})
      .map(([k, v]) => `<span class="f${isMasked(v) ? ' masked' : ''}">${esc(k)}=<b>${esc(v)}</b></span>`)
      .join(' ');
    const msg = r.msg ? `<span class="msg">| ${esc(r.msg)}</span>` : '';
    const cut = r.truncated ? '<span class="cut">[cut]</span>' : '';
    return `<div class="${cls}">${ts}${lvl}<span class="dom">${esc(r.domain)}</span>` +
           `<span class="evt">${esc(r.event)}</span>${fields}${msg}${cut}</div>`;
  }
  if (r.kind === 'unstructured') {
    return `<div class="${cls}">${ts}${lvl}<span class="tag">${esc(r.tag)}</span>` +
           `<span class="body">${esc(r.msg || '')}</span></div>`;
  }
  return `<div class="${cls}"><span class="body">${esc(r.raw)}</span></div>`;
}

const isMasked = (v) => v === '***';
const shortTs = (ts) => (ts.length > 12 ? ts.slice(-12) : ts);

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/* ── 이슈 트레이 ───────────────────────────────────── */
let pollTick = 0;

async function pollIssues() {
  if (state.paused) return;
  try {
    const snap = await (await fetch('/api/snapshot?limit=1')).json();
    state.issues = snap.issues;
    renderTray();
    // 앱이 재시작되면 pid 가 바뀐다. 소스가 다시 풀어준 값을 이따금 따라잡는다.
    if (++pollTick % 4 === 0) {
      const cfg = await (await fetch('/api/config')).json();
      const seen = (cfg.source && cfg.source.pids) || [];
      if ((cfg.source && cfg.source.pid) !== state.pid
          || seen.length !== state.pids.length) {
        $('src').textContent = describeSource(cfg.source);
        applyPid(cfg.source);
        state.dirty = true;
      }
    }
  } catch (_) {}
}

function renderTray() {
  const el = $('tray');
  if (!state.issues.length) { el.innerHTML = '<p class="empty">아직 이슈 없음</p>'; return; }
  el.innerHTML = state.issues.map((g) => {
    const on = state.issueFilter &&
               state.issueFilter.ruleId === g.ruleId && state.issueFilter.key === g.key;
    return `<div class="issue${on ? ' on' : ''}" data-rule="${esc(g.ruleId)}" data-key="${esc(g.key)}">
      <div class="top"><span class="sev ${esc(g.severity)}">${esc(g.ruleLabel)}</span>
      <span class="n">×${g.count}</span></div>
      <div class="k">${esc(g.key)}</div>
      <div class="s">${esc(g.sample || '')}</div></div>`;
  }).join('');
  for (const node of el.querySelectorAll('.issue')) {
    node.onclick = () => {
      const f = { ruleId: node.dataset.rule, key: node.dataset.key };
      const same = state.issueFilter && state.issueFilter.ruleId === f.ruleId &&
                   state.issueFilter.key === f.key;
      state.issueFilter = same ? null : f;
      renderTray(); state.dirty = true;
    };
  }
}

/* ── 대시보드 ──────────────────────────────────────── */
async function openDash() {
  $('dash').hidden = false;
  $('dashBody').innerHTML = '<p class="nodata">집계 중…</p>';
  const s = await (await fetch('/api/stats')).json();
  $('dashBody').innerHTML = dashHtml(s);
}

function dashHtml(s) {
  const pct = (x) => (x == null ? '—' : (x * 100).toFixed(1) + '%');
  const cards = [];

  cards.push(card('개요', `<div class="kpi">
    <div><span class="v">${s.total}</span><span class="l">총 줄</span></div>
    <div><span class="v">${s.structured}</span><span class="l">구조화</span></div>
    <div><span class="v">${pct(s.structuredRatio)}</span><span class="l">구조화 비율</span></div>
    <div><span class="v">${(s.levels || {}).E || 0}</span><span class="l">ERROR</span></div>
  </div>`));

  cards.push(card('도메인 빈도', bars(s.domains.map(([d, n]) => [d, n]))));

  cards.push(card('성공률', s.successRates.length ? s.successRates.map((r) => {
    const p = r.rate == null ? 0 : r.rate;
    return `<div class="brow"><span class="nm">${esc(r.domain)}</span>
      <span class="track"><span class="fill ${p >= 0.9 ? 'ok' : 'bad'}" style="width:${p * 100}%"></span></span>
      <span class="val">${pct(r.rate)} (${r.success}/${r.success + r.failure})</span></div>`;
  }).join('') : '<p class="nodata">성공/실패 접미사(_OK/_FAIL 등)를 가진 이벤트가 없습니다</p>'));

  cards.push(card('상위 이벤트', bars(s.topEvents)));

  for (const fr of s.failureReasons) {
    cards.push(card(`실패 사유 · ${esc(fr.domain)}`, bars(fr.reasons)));
  }

  for (const f of s.funnels) {
    const max = Math.max(1, ...f.steps.map((x) => x.count));
    cards.push(card(`퍼널 · ${esc(f.label)} <span class="hint">${f.mode === 'flowId' ? 'flowId 기준' : '단순 카운트'}</span>`,
      `<div class="funnel">` + f.steps.map((st) => `<div class="brow">
        <span class="nm">${esc(st.event)}</span>
        <span class="track"><span class="fill" style="width:${(st.count / max) * 100}%"></span></span>
        <span class="val">${st.count}${st.dropoff ? ` <span class="drop">-${(st.dropoff * 100).toFixed(0)}%</span>` : ''}</span>
      </div>`).join('') + `</div>`, true));
  }

  return cards.join('');
}

function card(title, body, wide) {
  return `<div class="card${wide ? ' wide' : ''}"><h3>${title}</h3>${body}</div>`;
}

function bars(pairs) {
  if (!pairs || !pairs.length) return '<p class="nodata">데이터 없음</p>';
  const max = Math.max(...pairs.map((p) => p[1]));
  return pairs.map(([name, n]) => `<div class="brow">
    <span class="nm">${esc(name)}</span>
    <span class="track"><span class="fill" style="width:${(n / max) * 100}%"></span></span>
    <span class="val">${n}</span></div>`).join('');
}

boot();
