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
  treeRaw: null,          // 마지막으로 받은 /api/tree 원문. 바뀔 때만 다시 그린다
  treeDirty: true,
  tbl: null,              // 열린 표 {table, gid, cmp, diff, q, show, recvOrder, showSame}
  dirty: true,
};

/* ── 부팅 ──────────────────────────────────────────── */
async function boot() {
  state.cfg = await (await fetch('/api/config')).json();
  // 표 기능이 없는 서버(재시작 전 구버전)도 cfg.tables 가 없을 뿐 나머지는 그대로 돈다.
  state.cfg.tables = state.cfg.tables || [];
  $('btnTables').hidden = !state.cfg.tables.length;
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
  // 줄이 다시 만들어져도 살아남도록 창에 한 번만 건다.
  $('treePane').addEventListener('click', onTreeClick);
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
    d.onclick = () => { state.tab = t.id; buildTabs(); state.treeDirty = true; state.dirty = true; };
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
  $('btnTables').onclick = () => openTable(null, null);
  $('tblClose').onclick = () => { $('tbl').hidden = true; };
  $('tblGroup').onchange = (e) => { state.tbl.gid = e.target.value; loadDiff(); };
  $('tblCmp').onchange = (e) => { state.tbl.cmp = e.target.value; loadDiff(); };
  $('tblQ').oninput = (e) => { state.tbl.q = e.target.value; renderTableBody(); };
  $('tblShow').onchange = (e) => { state.tbl.show = e.target.value; renderTableBody(); };
  $('tblRecv').onchange = (e) => { state.tbl.recvOrder = e.target.checked; renderTableBody(); };
  $('tblSame').onchange = (e) => { state.tbl.showSame = e.target.checked; renderTableBody(); };
  // 표 본문은 타이머로 다시 그리지 않으므로 click 으로 충분하다
  $('tblHist').onchange = (e) => { state.tbl.hist = e.target.checked; loadDiff(); };
  $('tblFlip').onchange = (e) => { state.tbl.flip = e.target.checked; renderTableBody(); };
  $('tblMd').onclick = () => exportTable('md');
  $('tblCsv').onclick = () => exportTable('csv');
  $('tblSave').onclick = async () => {
    const s = state.tbl;
    const res = await fetch(`/api/tables/save?table=${encodeURIComponent(s.table.id)}` +
                            `&group=${encodeURIComponent(s.gid)}`, { method: 'POST' }).catch(() => null);
    flash(res && res.ok ? '저장했습니다' : '저장하지 못했습니다');
    if (res && res.ok) openTable(s.table.id, s.gid);
  };
  $('tblReload').onclick = async () => {
    const s = state.tbl;
    const res = await fetch('/api/catalog/reload', { method: 'POST' }).catch(() => null);
    const d = res && res.ok ? await res.json() : null;
    const r = d && d[s.table.id];
    flash(r ? (r.error ? `못 읽음: ${r.error}` : `소스에서 ${r.found}개 읽음`) : '다시 읽지 못했습니다');
    openTable(s.table.id, s.gid);
  };
  $('tblBody').addEventListener('click', (e) => {
    const b = e.target.closest('.code, .klink, .hc');
    if (b) openDetail(b.dataset.k, b.dataset.g);
  });
  $('detClose').onclick = () => { $('det').hidden = true; };
  $('detBody').addEventListener('click', async (e) => {
    const o = e.target.closest('.srcopen');
    if (o) {
      const msg = o.parentElement.querySelector('.srcmsg');
      msg.textContent = ' 여는 중…';
      const u = `/api/open?table=${encodeURIComponent(state.tbl.table.id)}&code=${encodeURIComponent(o.dataset.code)}`;
      const res = await fetch(u, { method: 'POST' }).catch(() => null);
      const d = res ? await res.json().catch(() => ({})) : {};
      msg.textContent = res && res.ok ? ' 편집기에서 열었습니다' : ` 못 열었습니다: ${d.error || '서버 응답 없음'}`;
      msg.classList.toggle('bad', !(res && res.ok));
      return;
    }
    const b = e.target.closest('.rcopy');
    if (!b) return;
    const r = (state.detRows || [])[Number(b.dataset.i)];
    if (!r) return;
    try { await navigator.clipboard.writeText(r.raw); b.textContent = '복사됨'; }
    catch (_) { b.textContent = '복사 실패'; }
    setTimeout(() => { b.textContent = '복사'; }, 1200);
  });
  // 창 바깥(어두운 배경)을 누르면 닫는다. 안쪽을 누른 것은 무시한다.
  for (const id of ['det', 'tbl', 'dash']) {
    $(id).addEventListener('click', (e) => { if (e.target === $(id)) $(id).hidden = true; });
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeTop(); });
  // 접힌 묶음 줄은 0.1초마다 새로 그려진다. click 은 누른 요소와 뗀 요소가 같아야 성립해서
  // 그 사이에 줄이 갈리면 씹힌다 (트리에서 겪은 것과 같다). 누르는 순간에 처리한다.
  $('logs').addEventListener('mousedown', (e) => {
    const g = e.button === 0 && e.target.closest('.grp');
    if (!g) return;
    e.preventDefault();
    openTable(g.dataset.t, g.dataset.g);
  });
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
  // 로그가 들어올 때마다 트리까지 다시 그리면 안 된다. 트리 내용이 바뀐 경우만.
  if (tree && state.treeDirty) { renderTree(tree); state.treeDirty = false; }

  const slice = collapseGroups(shown).slice(-MAX_RENDER);
  const logs = $('logs');
  const cols = columnWidths(slice);
  logs.style.setProperty('--w-dom', cols.dom + 2 + 'ch');   // 배지 좌우 여백만큼
  logs.style.setProperty('--w-evt', cols.evt + 'ch');
  logs.innerHTML = slice.map((r) => rowHtml(r, cols)).join('');
  if (state.autoscroll) logs.scrollTop = logs.scrollHeight;
}

/* 표 규칙에 걸리는 줄은 묶음(groupBy)마다 한 줄로 접는다.
   붙어 있는 줄끼리가 아니라 같은 묶음끼리 접는다. 전체 탭에서는 시스템 로그가 사이사이 끼어서
   붙어 있는 줄 기준이면 한 묶음이 요약 여러 개로 쪼개진다.
   검색 중에는 접지 않는다. 찾은 줄이 요약 안에 숨으면 검색한 의미가 없다. */
function tableOfRec(r) {
  if (r.kind !== 'structured') return null;
  return state.cfg.tables.find((t) => t.domain === r.domain && (t.events || []).includes(r.event)) || null;
}

function collapseGroups(rows) {
  if (!state.cfg.tables.length || state.q) return rows;
  const out = [];
  const seen = new Map();
  for (const r of rows) {
    const t = tableOfRec(r);
    if (!t) { out.push(r); continue; }
    const gid = t.groupBy ? (r.fields[t.groupBy] ?? '') : '';
    const k = t.id + '\u0000' + gid;
    const g = seen.get(k);
    if (g) { g.count++; continue; }
    const item = { kind: 'group', table: t, gid, first: r, count: 1 };
    seen.set(k, item);
    out.push(item);
  }
  return out;
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
    // 원문 그대로 비교한다. 같으면 다시 그릴 이유가 없다 —
    // 괜히 다시 그리면 그 순간 누르고 있던 클릭이 취소된다(아래 toggleNode 주석 참고).
    const txt = await (await fetch('/api/tree')).text();
    if (txt === state.treeRaw) return;
    state.treeRaw = txt;
    state.treeData = {};
    for (const t of JSON.parse(txt)) state.treeData[t.id] = t;
    state.treeDirty = true;
    if (treeOfTab(state.tab)) state.dirty = true;
  } catch (_) {}
}

function renderTree(cfgTree) {
  const t = state.treeData && state.treeData[cfgTree.id];
  const el = $('treePane');
  if (!t) { el.innerHTML = '<p class="empty">세우는 중…</p>'; return; }
  if (!t.nodeCount) {
    el.innerHTML = '<p class="empty">아직 계층 로그가 없습니다. 앱에서 해당 화면을 펼쳐 보세요.</p>';
    return;
  }
  const keepScroll = el.scrollTop;
  const sum = `<div class="tsum">
    <span>노드 <b>${t.nodeCount}</b></span>
    <span>뿌리 <b>${t.rootCount}</b></span>
    <span>최대 깊이 <b>${t.maxDepth}</b></span>
    ${t.scopeCount > 1 ? `<span>조직 <b>${t.scopeCount}</b></span>` : ''}
    ${t.missingTotal ? `<span class="warn" title="앱이 알려준 자식 수와 실제로 본 수의 차이입니다. 앱이 세는 기준이 다르면 실제보다 크게 나올 수 있습니다.">아직 못 본 자식 <b>${t.missingTotal}</b></span>` : ''}
    ${t.truncatedTotal ? `<span class="warn" title="인원이 많아 로그에 남기지 않은 수입니다.">로그에 없는 인원 <b>${t.truncatedTotal}</b></span>` : ''}
    ${t.orphanCount ? `<span class="warn">부모 못 찾음 <b>${t.orphanCount}</b></span>` : ''}
    ${t.depthMismatch ? `<span class="warn" title="parent 로 세운 깊이가 앱이 적어 준 depth 와 다릅니다. parent 필드를 확인하세요.">깊이 불일치 <b>${t.depthMismatch}</b></span>` : ''}
    <span class="tacts">
      <button class="tact" data-all="open">모두 펼치기</button>
      <button class="tact" data-all="close">모두 접기</button>
    </span>
  </div>`;
  el.innerHTML = sum + t.roots.map(nodeHtml).join('');
  el.scrollTop = keepScroll;      // 주기적 갱신 때 읽던 자리를 잃지 않게
}

/* 접기/펼치기는 **DOM 을 직접 건드린다.** 다시 그려서는 안 된다.

   브라우저는 누른 곳과 뗀 곳이 같은 요소일 때만 click 을 발생시킨다.
   예전에는 이 트리를 통째로 innerHTML 로 다시 만들었는데, adb 로 로그가
   들어올 때마다 그게 일어났다. 누르는 0.1초 사이에 요소가 새것으로 갈리면
   브라우저는 클릭을 아예 취소한다 — 그래서 "터치가 씹히는" 것처럼 보였다.
   작은 +/- 가 특히 심했던 건 그걸 제일 자주 누르기 때문이다. */
function onTreeClick(e) {
  const act = e.target.closest('.tact');
  if (act) { setAllCollapsed(act.dataset.all === 'close'); return; }
  const row = e.target.closest('.tnode');
  if (row) toggleNode(row);
}

function toggleNode(row) {
  // 자식 묶음은 줄의 형제다 (nodeHtml 이 그렇게 만든다). 자식이 없으면 접을 것도 없다.
  const kids = row.nextElementSibling;
  if (!kids || !kids.classList.contains('tkids')) return;
  const collapse = !kids.classList.contains('hidden');
  kids.classList.toggle('hidden', collapse);
  const tog = row.querySelector('.tog');
  if (tog) tog.textContent = collapse ? '+' : '\u2212';
  // 다시 그릴 때 이 상태를 되살리기 위해 기억만 해 둔다.
  collapse ? state.collapsed.add(row.dataset.key) : state.collapsed.delete(row.dataset.key);
}

function setAllCollapsed(collapse) {
  // 모두 펼치기/접기도 같은 길을 쓴다. 여기만 다시 그리면 그 버튼도 똑같이 씹힌다.
  for (const row of $('treePane').querySelectorAll('.tnode')) {
    const kids = row.nextElementSibling;
    if (kids && kids.classList.contains('tkids')
        && kids.classList.contains('hidden') !== collapse) toggleNode(row);
  }
}

function nodeHtml(n) {
  const kids = n.children || [];
  // 같은 식별자가 다른 조직에 있을 수 있다. 접힘 상태도 조직까지 묶어서 기억한다.
  const key = `${n.scope || ''}\u0000${n.id}`;
  const isCollapsed = state.collapsed.has(key);
  const tog = kids.length
    ? `<span class="tog" aria-hidden="true">${isCollapsed ? '+' : '\u2212'}</span>`
    : '<span class="tog leaf" aria-hidden="true">·</span>';
  const metrics = Object.entries(n.metrics || {})
    .map(([k, v]) => `<span class="tw-m">${esc(k)}=${esc(v)}</span>`).join(' ');
  // 앱이 알려준 자식 수와 실제로 본 수의 차이. 앱이 세는 기준이 다를 수 있어
  // 실제보다 크게 나올 수 있다 — 그래서 "안 펼침" 이 아니라 "아직 못 봄" 으로 적는다.
  const more = n.missing
    ? `<span class="tw-more" title="앱이 자식 ${n.expected}개라고 했는데 ${n.children.length}개만 봤습니다. 앱이 세는 기준이 다르면 실제보다 크게 나올 수 있습니다.">+${n.missing} 미관측</span>`
    : '';
  const bad = n.depthMismatch
    ? `<span class="tw-more" style="color:var(--e);background:rgba(248,113,113,.12)">깊이 ${n.depth}≠${n.loggedDepth}</span>` : '';
  const cut = n.truncated
    ? `<span class="tw-more" title="인원이 많아 ${n.truncated}명은 로그에 남지 않았습니다.">${n.truncated}명 미기록</span>` : '';
  const sub = kids.length
    ? `<div class="tkids${isCollapsed ? ' hidden' : ''}">${kids.map(nodeHtml).join('')}</div>` : '';
  const isLeaf = n.kind === 'leaf';
  return `<div class="tnode${n.orphan ? ' orphan' : ''}${isLeaf ? ' person' : ''}" data-key="${esc(key)}"
      title="${n.orphan ? '부모 줄을 아직 못 봤습니다' : ''}">
      ${tog}<span class="tw-id">${esc(n.id)}</span>
      ${n.name ? `<span class="tw-name">${esc(n.name)}</span>` : ''}
      ${metrics}${more}${cut}${bad}
      ${n.hits > 1 ? `<span class="tw-hits">×${n.hits}</span>` : ''}
    </div>${sub}`;
}

/* 세로줄 맞추기. 줄마다 폭이 제각각이면 같은 필드가 매번 다른 자리에 찍혀 눈으로 훑을 수가 없다.
   도메인·이벤트 열은 화면 전체에서, 필드 열은 같은 이벤트끼리 폭을 맞춘다.
   폭은 지금 그리는 줄 중 가장 긴 값 — 상한을 넘는 값은 자기 칸 안에서 접힌다. */
const DOM_MAX_CH = 12;
const EVT_MAX_CH = 24;
const FIELD_MAX_CH = 40;

/* 고정폭 글꼴에서 한글·한자·전각 문자는 두 칸을 차지한다. 글자 수로 세면 칸이 모자라 접힌다. */
function dispWidth(s) {
  let w = 0;
  for (const ch of String(s)) {
    const c = ch.codePointAt(0);
    const wide = (c >= 0x1100 && c <= 0x115F) || (c >= 0x2E80 && c <= 0xA4CF) ||
                 (c >= 0xAC00 && c <= 0xD7A3) || (c >= 0xF900 && c <= 0xFAFF) ||
                 (c >= 0xFF00 && c <= 0xFF60) || (c >= 0xFFE0 && c <= 0xFFE6);
    w += wide ? 2 : 1;
  }
  return w;
}

function columnWidths(rows) {
  const cols = { dom: 4, evt: 6, byEvt: new Map() };
  for (const row of rows) {
    const r = row.kind === 'group' ? row.first : row;
    if (r.kind !== 'structured') continue;
    cols.dom = Math.max(cols.dom, Math.min(dispWidth(r.domain || ''), DOM_MAX_CH));
    cols.evt = Math.max(cols.evt, Math.min(dispWidth(r.event || '') + 1, EVT_MAX_CH));
    let w = cols.byEvt.get(r.event);
    if (!w) cols.byEvt.set(r.event, (w = new Map()));
    for (const [k, v] of Object.entries(r.fields || {})) {
      // +1 은 여유분. 딱 맞게 잡으면 소수점 반올림으로 마지막 글자가 다음 줄로 넘어간다.
      const n = Math.min(dispWidth(k + '=' + (v ?? '')) + 1, FIELD_MAX_CH);
      if (n > (w.get(k) || 0)) w.set(k, n);
    }
  }
  return cols;
}

function rowHtml(r, cols) {
  if (r.kind === 'group') return groupRowHtml(r);
  const cls = `row lv-${r.level}` + (r.kind === 'raw' ? ' raw' : '');
  // 시각이 없는 줄도 칸은 비워 둔다. 빼면 뒤 열이 전부 한 칸씩 당겨진다.
  const ts = `<span class="ts">${r.ts ? esc(shortTs(r.ts)) : ''}</span>`;
  const lvl = `<span class="lvl">${r.level}</span>`;

  if (r.kind === 'structured') {
    const widths = (cols && cols.byEvt.get(r.event)) || new Map();
    const entries = Object.entries(r.fields || {});
    const fields = entries
      .map(([k, v], i) => {
        const w = widths.get(k);
        // 마지막 필드는 남는 폭을 다 쓴다. 긴 URL 이 좁은 칸에서 여러 줄로 접히지 않게.
        const last = i === entries.length - 1 && !r.msg;
        const style = w ? ` style="flex:${last ? 1 : 0} 0 ${w}ch"` : '';
        return `<span class="f${isMasked(v) ? ' masked' : ''}"${style}>${esc(k)}=<b>${esc(v)}</b></span>`;
      })
      .join('');
    const msg = r.msg ? `<span class="msg">| ${esc(r.msg)}</span>` : '';
    const cut = r.truncated ? '<span class="cut">[cut]</span>' : '';
    return `<div class="${cls}">${ts}${lvl}<span class="dom">${esc(r.domain)}</span>` +
           `<span class="evt">${esc(r.event)}</span><span class="fs">${fields}${msg}${cut}</span></div>`;
  }
  if (r.kind === 'unstructured') {
    return `<div class="${cls}">${ts}${lvl}<span class="tag">${esc(r.tag)}</span>` +
           `<span class="body">${esc(r.msg || '')}</span></div>`;
  }
  return `<div class="${cls}"><span class="body">${esc(r.raw)}</span></div>`;
}

/* 접힌 묶음 한 줄. 첫 줄의 시각·도메인·이벤트 자리에 그대로 서서 열이 흐트러지지 않는다. */
function groupRowHtml(g) {
  const f = g.first;
  const by = g.table.groupBy
    ? `<span class="f">${esc(g.table.groupBy)}=<b>${esc(g.gid)}</b></span>` : '';
  return `<div class="row lv-${f.level} grp" data-t="${esc(g.table.id)}" data-g="${esc(g.gid)}">` +
    `<span class="ts">${f.ts ? esc(shortTs(f.ts)) : ''}</span><span class="lvl">${f.level}</span>` +
    `<span class="dom">${esc(f.domain)}</span><span class="evt">${esc(f.event)}</span>` +
    `<span class="fs"><span class="gcount">×${g.count}</span>${by}` +
    `<span class="gopen">${esc(g.table.label)} 표로 보기 ▸</span></span></div>`;
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

/* ── 표 ────────────────────────────────────────────── */
/* 로그 목록과 달리 타이머로 다시 그리지 않는다. 열 때와 조작할 때만 그린다.
   select 가 열린 채로 다시 만들어지면 닫혀 버리고, 입력칸은 포커스를 잃는다.
   그래서 조작부는 열 때 한 번만 만들고, 조작할 때는 본문만 다시 그린다. */
async function openTable(tid, gid) {
  $('tbl').hidden = false;
  $('tblBody').innerHTML = '<p class="nodata">불러오는 중…</p>';
  let tables;
  try {
    const res = await fetch('/api/tables');
    if (!res.ok) throw new Error(String(res.status));
    tables = await res.json();
  } catch (_) {
    $('tblBody').innerHTML = '<p class="nodata">표를 불러오지 못했습니다. ' +
      '뷰어 서버가 이 기능보다 오래된 버전이면 재시작해야 합니다.</p>';
    return;
  }
  const t = tables.find((x) => x.id === tid) || tables[0];
  if (!t || !t.groups.length) {
    $('tblBody').innerHTML = '<p class="nodata">아직 모인 묶음이 없습니다</p>';
    return;
  }
  const g = t.groups.find((x) => x.id === gid) || t.groups[t.groups.length - 1];
  const prev = state.tbl || {};
  state.tbl = { table: t, gid: g.id, cmp: '', diff: null, q: prev.q || '',
                show: prev.show || 'all', recvOrder: !!prev.recvOrder, showSame: !!prev.showSame,
                hist: !!prev.hist, flip: !!prev.flip, export: null };

  $('tblTitle').textContent = t.label;
  const saved = t.groups.filter((x) => x.saved).length;
  $('tblHint').textContent = `묶음 ${t.groups.length}개${saved ? ` (저장 ${saved})` : ''} · 행 = ${t.key}` +
    (t.catalogError ? ` · 구현 목록 못 읽음: ${t.catalogError}` : '');
  $('tblReload').hidden = !t.sourceRoot;
  fillGroupSelects();
  $('tblQ').value = state.tbl.q;
  $('tblShow').value = state.tbl.show;
  $('tblRecv').checked = state.tbl.recvOrder;
  $('tblSame').checked = state.tbl.showSame;
  $('tblHist').checked = state.tbl.hist;
  $('tblFlip').checked = state.tbl.flip;
  renderTableBody();
}

function fillGroupSelects() {
  const s = state.tbl;
  const opts = s.table.groups.map((x) => `<option value="${esc(x.id)}">${esc(groupLabel(x))}</option>`).join('');
  $('tblGroup').innerHTML = opts;
  $('tblGroup').value = s.gid;
  $('tblCmp').innerHTML = '<option value="">비교 안 함</option>' + opts;
  $('tblCmp').value = s.cmp;
}

/* 묶음 이름: 계정(labelFrom)이 있으면 그걸 앞에. flowId 는 같은 계정 여러 번을 가를 때만 필요하다. */
function groupLabel(g) {
  const when = g.firstTs ? shortTs(g.firstTs).slice(0, 8) : '';
  const who = g.label ? `${g.label} (${String(g.id).slice(0, 6)})` : (g.id || '(묶음 없음)');
  const tags = [];
  if (g.saved) tags.push('저장됨');
  if (g.complete === false) tags.push(`${g.count}/${g.expected} 일부만`);
  if (g.problemCount) tags.push(`형식 문제 ${g.problemCount}`);
  return `${who} · ${when} · ${g.count}개${tags.length ? ' · ' + tags.join(' · ') : ''}`;
}

function curGroup() {
  const s = state.tbl;
  return s && s.table.groups.find((x) => x.id === s.gid);
}

/* 비교는 "비교 대상(A) → 지금 보는 묶음(B)" 방향이다. 추가는 B 에만 있는 것. */
async function loadDiff() {
  const s = state.tbl;
  if (!s) return;
  s.diff = null;
  if (s.cmp && s.cmp !== s.gid && !s.hist) {
    $('tblBody').innerHTML = '<p class="nodata">비교 중…</p>';
    try {
      const u = `/api/tables/diff?table=${encodeURIComponent(s.table.id)}` +
                `&a=${encodeURIComponent(s.cmp)}&b=${encodeURIComponent(s.gid)}`;
      const res = await fetch(u);
      const d = await res.json();
      if (!res.ok) {
        $('tblBody').innerHTML = `<p class="nodata">${esc(d.error || '비교하지 못했습니다')}</p>`;
        return;
      }
      s.diff = d;
    } catch (_) {
      $('tblBody').innerHTML = '<p class="nodata">비교하지 못했습니다</p>';
      return;
    }
  }
  renderTableBody();
}

function renderTableBody() {
  const s = state.tbl;
  if (!s) return;
  $('tblSameWrap').hidden = !s.diff || s.hist;
  $('tblFlipWrap').hidden = !s.hist;
  // 이력은 묶음 전체를 가로로 보는 것이라 묶음·비교 선택이 의미가 없다
  $('tblGroup').disabled = s.hist;
  $('tblCmp').disabled = s.hist;
  const g = curGroup();
  $('tblSave').hidden = !(state.cfg.snapshots && g && !g.saved && !s.hist);
  $('tblBody').innerHTML = s.hist ? histHtml(s) : s.diff ? diffHtml(s) : groupHtml(s);
}

const isNil = (v) => v == null || v === '' || v === '-';

function rowHit(s, key, valueObjs) {
  if (!s.q) return true;
  const q = s.q.toLowerCase();
  if (String(key).toLowerCase().includes(q)) return true;
  return valueObjs.some((o) => Object.values(o).some((v) => String(v).toLowerCase().includes(q)));
}

// 가나다순. 숫자는 크기대로 — FEAT_USER_2 가 FEAT_USER_10 보다 앞에 온다.
const KEY_ORDER = new Intl.Collator('ko', { numeric: true, sensitivity: 'base' });
function byKey(a, b) { return KEY_ORDER.compare(String(a.key), String(b.key)); }

const ST_LABEL = { on: '켜짐', off: '꺼짐', extra: '목록 밖' };

/* 한 묶음을 코드 단위로 모은다. 켜짐/꺼짐/목록 밖과 형식 문제 수를 같이 매긴다. */
function codeItems(t, g) {
  const cat = new Map((t.catalog || []).map((c) => [c.code, c]));
  const hasCat = cat.size > 0;
  const byCode = new Map();
  g.rows.forEach((r, i) => {
    if (!byCode.has(r.key)) byCode.set(r.key, { rows: [], first: i });
    byCode.get(r.key).rows.push(r);
  });
  const keys = new Set([...byCode.keys(), ...cat.keys()]);
  return [...keys].map((key) => {
    const got = byCode.get(key);
    const info = cat.get(key) || null;
    const rows = got ? got.rows : [];
    return {
      key, info, rows,
      first: got ? got.first : Infinity,
      st: got ? (hasCat && !info ? 'extra' : 'on') : 'off',
      bad: rows.reduce((n, r) => n + ((r.problems || []).length ? 1 : 0), 0),
    };
  });
}

function itemHit(s, it) {
  const extra = it.info && it.info.name ? [{ n: it.info.name }] : [];
  return rowHit(s, it.key, it.rows.map((r) => r.values).concat(extra));
}

/* 묶음 보기는 key(코드)만 늘어놓는다. 값까지 펼치면 긴 URL·JSON 이 섞여 한눈에 안 들어온다.
   값은 코드를 눌러 상세 창에서 본다. 같은 코드는 한 칸으로 모으고 몇 번 나왔는지 붙인다.

   구현 목록(catalog)이 있으면 "들어왔나" 로 불을 켜고 끈다. 값이 비어 있어도 들어오기만 하면
   동작하는 항목이 있어서, 값 유무로 흐리게 하면 멀쩡히 동작하는 것이 꺼진 것처럼 보인다.
     켜짐   목록에 있고 들어온 것
     꺼짐   목록에 있는데 이번 묶음에 안 들어온 것
     목록 밖 들어왔는데 목록에 없는 것 (앱이 처리하지 않는 항목)
   검색은 코드·이름·값까지 뒤진다 — 값으로 코드를 찾는 경우가 많다. */
function groupHtml(s) {
  const t = s.table;
  const g = curGroup();
  if (!g) return '<p class="nodata">이 묶음이 버퍼에서 밀려났습니다</p>';
  const hasCat = (t.catalog || []).length > 0;
  let items = codeItems(t, g);
  const n = { on: 0, off: 0, extra: 0, bad: 0 };
  for (const it of items) { n[it.st]++; if (it.bad) n.bad++; }

  items = items.filter((it) => (s.show === 'all' || (s.show === 'bad' ? it.bad : it.st === s.show)) &&
                               itemHit(s, it));
  // 받은 순서로 보면 안 들어온 것은 맨 뒤로 간다. 그 안에서는 가나다순.
  items.sort(s.recvOrder ? (a, b) => (a.first - b.first) || byKey(a, b) : byKey);

  const cols = t.columns || [];
  s.export = {
    name: `${t.id}-${g.label || g.id}`,
    head: [t.key, '이름', '상태', '횟수'].concat(cols, ['형식 문제']),
    rows: items.map((it) => [it.key, (it.info && it.info.name) || '', ST_LABEL[it.st], String(it.rows.length)]
      .concat(cols.map((c) => it.rows.map((r) => r.values[c] ?? '').join(' / ')),
              [it.rows.flatMap((r) => r.problems || []).join('; ')])),
  };

  const TITLE = { on: '들어옴', off: '이번 묶음에 안 들어옴', extra: '들어왔지만 구현 목록에 없음' };
  const cells = items.map((it) =>
    `<button class="code ${it.st}${it.bad ? ' bad' : ''}" data-k="${esc(it.key)}" data-g="${esc(g.id)}"` +
    ` title="${TITLE[it.st]}${it.bad ? ' · 형식 문제 있음' : ''} · 눌러서 상세 보기">` +
    '<i class="lamp"></i>' +
    `<span class="cbody"><span class="ck">${esc(it.key)}</span>` +
    (it.info && it.info.name ? `<span class="cname">${esc(it.info.name)}</span>` : '') + '</span>' +
    (it.bad ? '<span class="cbad">⚠</span>' : '') +
    (it.rows.length > 1 ? `<b class="cn">×${it.rows.length}</b>` : '') +
    (it.st === 'extra' ? '<span class="ctag">목록 밖</span>' : '') +
    '</button>').join('');

  const counts = (hasCat
    ? `<span class="lc on">켜짐 ${n.on}</span><span class="lc off">꺼짐 ${n.off}</span>` +
      (n.extra ? `<span class="lc extra">목록 밖 ${n.extra}</span>` : '') +
      `<span class="lc">구현 목록 ${(t.catalog || []).length}개 · 받은 줄 ${g.rows.length}개</span>`
    : `<span class="lc">코드 ${n.on}개 · 받은 줄 ${g.rows.length}개</span>` +
      '<span class="lc hint2">구현한 코드 목록(설정의 catalog)을 넣으면 안 들어온 것이 꺼진 불로 보입니다</span>') +
    (n.bad ? `<span class="lc bad">형식 문제 ${n.bad}</span>` : '') +
    (g.saved ? `<span class="lc">저장됨 ${esc((g.savedAt || '').replace('T', ' ').slice(0, 16))}</span>` : '');
  return completeNote(g) + `<p class="tcount">${counts}</p>` +
    (items.length ? `<div class="codes">${cells}</div>` : '<p class="nodata">일치하는 코드 없음</p>');
}

/* 이력: 코드 × 묶음(로그인). 간헐적으로 안 내려오는 항목을 찾는 화면이다.
   묶음이 많으면 최근 것만 — 가로로 끝없이 늘어나면 못 읽는다. */
const HIST_MAX = 30;

function histHtml(s) {
  const t = s.table;
  const groups = t.groups.slice(-HIST_MAX);
  const cat = new Map((t.catalog || []).map((c) => [c.code, c]));
  const got = groups.map((g) => {
    const m = new Map();
    for (const r of g.rows) m.set(r.key, (m.get(r.key) || 0) + 1);
    return m;
  });
  const keys = new Set(cat.keys());
  for (const m of got) for (const k of m.keys()) keys.add(k);
  let rows = [...keys].map((key) => {
    const marks = got.map((m) => m.has(key));
    const on = marks.filter(Boolean).length;
    return { key, info: cat.get(key) || null, marks, on, flip: on > 0 && on < marks.length };
  });
  const flips = rows.filter((r) => r.flip).length;
  rows = rows.filter((r) => (!s.flip || r.flip) &&
    rowHit(s, r.key, r.info && r.info.name ? [{ n: r.info.name }] : []));
  rows.sort(byKey);

  s.export = {
    name: `${t.id}-이력`,
    head: [t.key, '이름', '켜진 횟수'].concat(groups.map((g) => groupLabel(g))),
    rows: rows.map((r) => [r.key, (r.info && r.info.name) || '', `${r.on}/${groups.length}`]
      .concat(r.marks.map((x) => (x ? '●' : '○')))),
  };

  const head = '<tr><th class="hk">' + esc(t.key) + '</th><th class="hn">켜짐</th>' +
    groups.map((g, i) => `<th class="hg" title="${esc(groupLabel(g))}">${i + 1}<br>` +
      `<span>${esc(g.label ? String(g.label).split('@')[0].slice(0, 8) : (g.firstTs ? shortTs(g.firstTs).slice(0, 5) : ''))}</span></th>`).join('') +
    '</tr>';
  const body = rows.map((r) => `<tr class="${r.flip ? 'flip' : ''}">` +
    `<td class="hk"><span class="ck">${esc(r.key)}</span>` +
    (r.info && r.info.name ? `<span class="cname">${esc(r.info.name)}</span>` : '') + '</td>' +
    `<td class="hn">${r.on}/${groups.length}</td>` +
    r.marks.map((x, i) => `<td><button class="hc ${x ? 'on' : 'off'}" data-k="${esc(r.key)}" ` +
      `data-g="${esc(groups[i].id)}" title="${esc(groupLabel(groups[i]))}"></button></td>`).join('') +
    '</tr>').join('');
  return `<p class="tcount"><span class="lc">최근 묶음 ${groups.length}개${t.groups.length > HIST_MAX ? ` (전체 ${t.groups.length}개 중)` : ''}</span>` +
    `<span class="lc extra">바뀐 코드 ${flips}</span>` +
    '<span class="lc hint2">칸을 누르면 그 묶음의 상세. 머리글에 마우스를 올리면 묶음 이름</span></p>' +
    (rows.length ? `<div class="histwrap"><table class="hist"><thead>${head}</thead><tbody>${body}</tbody></table></div>`
                 : '<p class="nodata">일치하는 코드 없음</p>');
}

/* ── 내보내기 ──────────────────────────────────────── */
/* 지금 화면에 보이는 그대로(필터·정렬 반영)를 내보낸다. 서버 팀에 넘길 때 쓴다. */
function exportTable(kind) {
  const s = state.tbl;
  const x = s && s.export;
  if (!x || !x.rows.length) { flash('내보낼 행이 없습니다'); return; }
  if (kind === 'md') {
    const cell = (v) => String(v ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');
    const md = [x.head, x.head.map(() => '---')].concat(x.rows)
      .map((r) => '| ' + r.map(cell).join(' | ') + ' |').join('\n');
    navigator.clipboard.writeText(md)
      .then(() => flash(`Markdown ${x.rows.length}행 복사함`), () => flash('복사하지 못했습니다'));
    return;
  }
  const q = (v) => '"' + String(v ?? '').replace(/"/g, '""') + '"';
  // 엑셀이 한글을 깨지 않게 BOM 을 붙인다
  const csv = '\ufeff' + [x.head].concat(x.rows).map((r) => r.map(q).join(',')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  a.download = `${x.name}.csv`.replace(/[\\/:*?"<>|\s]+/g, '_');
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  flash(`CSV ${x.rows.length}행 저장`);
}

let flashTimer = 0;
function flash(msg) {
  $('tblMsg').textContent = msg;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { $('tblMsg').textContent = ''; }, 2500);
}

/* ── 상세 창 ───────────────────────────────────────── */
/* 코드 하나의 모든 것. 같은 코드가 여러 번 왔으면 전부 카드로 늘어놓는다.
   카드 맨 위에는 받은 줄을 해석 없이 그대로 둔다. 아래 표는 뷰어가 해석한 것이라
   파싱이 틀렸는지는 원본과 대조해야만 알 수 있다. */
function openDetail(key, gid) {
  const s = state.tbl;
  if (!s) return;
  const t = s.table;
  const g = t.groups.find((x) => x.id === gid);
  const rows = g ? g.rows.filter((r) => r.key === key) : [];
  const info = (t.catalog || []).find((c) => c.code === key) || null;
  $('detTitle').textContent = key;
  $('detHint').textContent = [
    info && info.name,
    g ? (g.label || (t.groupBy ? `${t.groupBy}=${g.id || '(없음)'}` : '')) : '',
    rows.length ? `${rows.length}건` : '안 들어옴',
  ].filter(Boolean).join(' · ');
  state.detRows = rows;
  const note = info && info.note ? `<p class="dnote">${esc(info.note)}</p>` : '';
  $('detBody').innerHTML = sourceLine(t, info) + note + (rows.length
    ? rows.map((r, i) => detailCard(t, g, r, i, rows.length)).join('')
    : `<div class="dcard offcard"><i class="lamp"></i><div><b>이번 묶음에 안 들어왔습니다</b>` +
      '<p>구현 목록에는 있지만 서버가 이 묶음에서 보내지 않았습니다. 이력 보기에서 다른 로그인과 견줘 보세요.</p></div></div>');
  $('det').hidden = false;
  $('detBody').scrollTop = 0;
}

/* 앱 코드 위치. 링크 틀(sourceLink)이 있으면 눌러서 편집기로 연다. */
function sourceLine(t, info) {
  if (!info || !info.where) return '';
  const cut = String(info.where).lastIndexOf(':');
  const path = cut > 0 ? info.where.slice(0, cut) : info.where;
  const line = cut > 0 ? info.where.slice(cut + 1) : '1';
  const abs = t.sourceRoot ? `${t.sourceRoot}/${path}` : path;
  const refs = info.refs > 1 ? ` · 참조 ${info.refs}곳` : '';
  const label = `${path.split('/').pop()}:${line}`;
  // 서버가 직접 여는 명령이 있으면 그걸 쓴다. 브라우저 링크는 어느 편집기가 받을지 고를 수 없다.
  if (t.sourceOpen) {
    return `<p class="dsrc">앱 코드 <button class="srcopen" data-code="${esc(info.code)}" title="${esc(abs)}">` +
           `${esc(label)} ↗</button>${refs}<span class="srcmsg"></span></p>`;
  }
  if (!t.sourceLink) {
    return `<p class="dsrc">앱 코드 <span title="${esc(abs)}">${esc(label)}</span>${refs}</p>`;
  }
  const url = t.sourceLink.replace('{abs}', encodeURI(abs)).replace('{path}', encodeURI(path))
                          .replace('{line}', encodeURIComponent(line));
  return `<p class="dsrc">앱 코드 <a href="${esc(url)}" title="${esc(abs)}">${esc(label)} ↗</a>${refs}</p>`;
}

function detailCard(t, g, r, i, n) {
  const fields = [[t.key, r.key]];
  if (t.groupBy) fields.push([t.groupBy, g.id]);
  for (const [k, v] of Object.entries(r.values)) fields.push([k, v]);
  const rows = fields.map(([k, v]) =>
    `<tr><th>${esc(k)}</th><td>${fmtDetail(v)}</td></tr>`).join('');
  const head = (n > 1 ? `<b>${i + 1} / ${n}</b>` : '') +
               (r.ts ? `<span>${esc(r.ts)}</span>` : '');
  const probs = (r.problems || []).length
    ? `<div class="dprob"><b>형식 문제</b>${r.problems.map((p) => `<div>${esc(p)}</div>`).join('')}</div>` : '';
  return `<div class="dcard">${head ? `<div class="dhead">${head}</div>` : ''}` + probs +
    (r.raw ? rawBox(r.raw, i) : '') +
    `<div class="dsec">해석</div><table class="ftable">${rows}</table></div>`;
}

/* 받은 줄 그대로. 한 줄은 너무 길어 읽을 수 없으니 필드마다 한 줄로 세운다.
   값은 손대지 않는다 (_ 치환, JSON, K=V 전부 받은 모양 그대로). 자르는 기준은 공백뿐이다 —
   형식상 값에는 공백이 없으므로 공백이 곧 필드 경계다. */
function rawBox(raw, i) {
  const at = raw.indexOf(' evt=');
  const prefix = at >= 0 ? raw.slice(0, at).trim() : '';
  let body = at >= 0 ? raw.slice(at + 1) : raw;
  let msg = '';
  const bar = body.indexOf(' | ');
  if (bar >= 0) { msg = body.slice(bar + 3); body = body.slice(0, bar); }
  const lines = body.split(/\s+/).filter(Boolean).map((tok) => {
    const eq = tok.indexOf('=');
    return eq > 0
      ? `<div class="rl"><span class="rk">${esc(tok.slice(0, eq))}</span><span class="req">=</span><span class="rv">${esc(tok.slice(eq + 1))}</span></div>`
      : `<div class="rl"><span class="rv">${esc(tok)}</span></div>`;
  }).join('');
  return '<div class="rawbox">' +
    `<div class="rawhead"><b>원본 로그</b><span>받은 그대로 · 필드마다 한 줄</span>` +
    `<button class="btn rcopy" data-i="${i}">복사</button></div>` +
    (prefix ? `<div class="rpre">${esc(prefix)}</div>` : '') +
    `<div class="rlines">${lines}</div>` +
    (msg ? `<div class="rmsg">| ${esc(msg)}</div>` : '') +
    `<details class="rone"><summary>한 줄로 보기</summary><pre>${esc(raw)}</pre></details>` +
    '</div>';
}

/* 상세 창의 값 표시. 표 칸(fmtVal)보다 넓으니 접지 않고 다 펼친다. */
function fmtDetail(v) {
  if (isNil(v)) return '<span class="nil">비어 있음 (-)</span>';
  const s = String(v);
  if (/^[[{]/.test(s)) {
    const obj = parseLooseJson(s);
    if (obj !== undefined) return `<pre class="jsfull">${esc(JSON.stringify(obj, null, 2))}</pre>`;
  }
  const parts = s.split(',');
  if (parts.every((p) => KV_PART.test(p))) {
    return '<table class="kvt">' + parts.map((p) => {
      const i = p.indexOf('=');
      const val = p.slice(i + 1);
      return `<tr><th>${esc(p.slice(0, i))}</th><td>${val ? esc(val) : '<span class="nil">∅</span>'}</td></tr>`;
    }).join('') + '</table>';
  }
  // 확장자 목록처럼 짧은 항목이 쉼표로 늘어선 것은 칩으로
  if (parts.length > 3 && parts.every((p) => p && p.length <= 24 && !p.includes('://'))) {
    return parts.map((p) => `<span class="kv">${esc(p)}</span>`).join('');
  }
  return `<span class="val">${esc(s)}</span>`;
}

function closeTop() {
  if (!$('det').hidden) { $('det').hidden = true; return; }
  if (!$('tbl').hidden) { $('tbl').hidden = true; return; }
  if (!$('dash').hidden) $('dash').hidden = true;
}

function completeNote(g) {
  if (g.complete === false) {
    return `<p class="twarn">앱은 ${g.expected}개를 보냈다고 찍었는데 ${g.count}개만 남아 있습니다. ` +
           '버퍼가 앞부분을 밀어냈을 수 있습니다.</p>';
  }
  return '';
}

const DIFF_LABEL = { added: '추가', removed: '삭제', changed: '변경', same: '같음' };

function diffHtml(s) {
  const d = s.diff;
  const cols = d.columns;
  const warn = (d.aComplete === false || d.bComplete === false)
    ? '<p class="twarn">한쪽 묶음이 일부만 남아 있습니다. 추가·삭제 중 일부는 버퍼에서 밀려난 탓일 수 있습니다.</p>'
    : '';
  const sm = d.summary;
  const line = `<p class="tsumline">` +
    ['added', 'removed', 'changed', 'same'].map((k) => `<span class="st ${k}">${DIFF_LABEL[k]} ${sm[k]}</span>`).join('') +
    '</p>';
  let rows = d.rows.filter((r) => (s.showSame || r.status !== 'same') &&
                                  rowHit(s, r.key, r.a.concat(r.b, r.common)));
  if (!s.recvOrder) rows = rows.slice().sort(byKey);
  const vals = (list) => list.map((o) =>
    `<div class="dv">${cols.map((c) => `<span class="dc"><i>${esc(c)}</i>${fmtVal(o[c])}</span>`).join('')}</div>`).join('');
  const common = (r) => (!r.common.length ? ''
    : r.status === 'same' ? vals(r.common)
    : `<div class="dcom">공통 ${r.common.length}개</div>`);
  // 삭제된 코드는 A 쪽에만 있으니 상세도 A 묶음에서 연다
  const body = rows.map((r) => `<tr class="st-${r.status}"><td class="k">` +
    `<button class="klink" data-k="${esc(r.key)}" data-g="${esc(r.status === 'removed' ? d.a : d.b)}">${esc(r.key)}</button></td>` +
    `<td><span class="st ${r.status}">${DIFF_LABEL[r.status]}</span></td>` +
    `<td>${vals(r.a)}${common(r)}</td><td>${vals(r.b)}${r.status === 'same' ? common(r) : ''}</td></tr>`).join('');
  const flat = (list) => list.map((o) => cols.map((c) => `${c}=${o[c] ?? ''}`).join(', ')).join(' / ');
  s.export = {
    name: `${s.table.id}-비교-${d.a}-${d.b}`,
    head: [s.table.key, '상태', `A ${d.a}`, `B ${d.b}`],
    rows: rows.map((r) => [r.key, DIFF_LABEL[r.status],
      flat(r.status === 'same' ? r.common : r.a), flat(r.status === 'same' ? r.common : r.b)]),
  };
  const head = `<tr><th>${esc(s.table.key)}</th><th>상태</th>` +
    `<th>A · ${esc(d.a || '(묶음 없음)')}</th><th>B · ${esc(d.b || '(묶음 없음)')}</th></tr>`;
  return warn + line + (rows.length
    ? `<table class="grid diff"><thead>${head}</thead><tbody>${body}</tbody></table>`
    : '<p class="nodata">차이 없음</p>');
}

/* 값 안쪽 구조를 풀어 보인다. 모르는 모양이면 원문 그대로 — 틀리게 푸는 것보다 낫다. */
const KV_PART = /^[A-Za-z0-9_.]+=/;

function fmtVal(v) {
  if (isNil(v)) return '<span class="nil">–</span>';
  const s = String(v);
  if (/^[[{]/.test(s)) {
    const obj = parseLooseJson(s);
    if (obj !== undefined) {
      const n = Array.isArray(obj) ? obj.length : Object.keys(obj).length;
      return `<details class="js"><summary>${Array.isArray(obj) ? '[…]' : '{…}'} ${n}개</summary>` +
             `<pre>${esc(JSON.stringify(obj, null, 2))}</pre></details>`;
    }
  }
  const parts = s.split(',');
  if (parts.every((p) => KV_PART.test(p))) {
    return parts.map((p) => {
      const i = p.indexOf('=');
      const val = p.slice(i + 1);
      return `<span class="kv"><i>${esc(p.slice(0, i))}</i>${val ? esc(val) : '<span class="nil">∅</span>'}</span>`;
    }).join('');
  }
  return `<span class="val">${esc(s)}</span>`;
}

/* emitter 는 값 안의 공백을 _ 로 바꿔 둔다. 그래서 JSON 이 그대로는 안 읽힌다.
   JSON 구분자 바로 옆의 _ 만 걷어낸다. 문자열 안의 _ 는 원래 공백이었는지 원래 _ 였는지
   알 수 없으니 건드리지 않는다. */
function parseLooseJson(s) {
  const loose = s.replace(/_(?=[,:\]}])/g, '').replace(/([,:[{])_/g, '$1');
  for (const cand of [s, loose]) {
    try {
      const o = JSON.parse(cand);
      if (o && typeof o === 'object') return o;
    } catch (_) { /* 다음 후보 */ }
  }
  return undefined;
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
