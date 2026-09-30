// Voice Vibe control panel. Plain ES module, no build step. Data from the hub
// is only ever inserted as text nodes / attributes, never as HTML.
const $ = (sel) => document.querySelector(sel);
let TOKEN = null;
let ws = null;
let timer = null;
let current = '';
const live = new Map(); // approval id -> {msg, record}, asked of this panel over the WebSocket
const LABEL = { ok: 'OK', user: 'needs you', fail: 'problem', unknown: 'not checked', down: 'down' };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, { method = 'GET', body } = {}) {
  const headers = { Authorization: `Bearer ${TOKEN}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(`/ui/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === 'string' ? d : (d && d.errors ? d.errors.join('\n') : `${res.status} ${res.statusText}`));
  }
  return data;
}

const enc = (id) => id.split('/').map(encodeURIComponent).join('/');
const newId = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random())).replace(/[^a-z0-9]/gi, '').slice(0, 12);
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : '');
const badge = (state, text) => h('span', { class: `badge ${state}` }, text || LABEL[state] || state);
const counts = (obj) => Object.entries(obj || {}).map(([k, v]) => `${v} ${k}`).join(', ') || 'none';
function left(ts) {
  if (!ts) return '';
  const hours = Math.max(0, Math.round((ts * 1000 - Date.now()) / 3600000));
  return hours < 1 ? 'within the hour' : `in ${hours} h`;
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function toast(text, kind = '') {
  const box = h('article', { class: kind }, text);
  $('#toasts').append(box);
  setTimeout(() => box.remove(), 7000);
}
function fail(e) { return h('article', { class: 'fail', role: 'alert' }, h('strong', {}, 'Could not load: '), e.message || String(e)); }
async function busy(button, fn) {
  button.setAttribute('aria-busy', 'true');
  button.disabled = true;
  try { return await fn(); } finally { button.removeAttribute('aria-busy'); button.disabled = false; }
}
function table(rows, cols) {
  if (!rows.length) return h('p', { class: 'muted' }, 'None.');
  return h('div', { class: 'overflow-auto' }, h('table', { class: 'striped' },
    h('thead', {}, h('tr', {}, cols.map(([, label]) => h('th', { scope: 'col' }, label)))),
    h('tbody', {}, rows.map((r) => h('tr', {}, cols.map(([key, , fmt]) => h('td', {}, fmt ? fmt(r[key], r) : (r[key] ?? ''))))))));
}

// ---- pages ---------------------------------------------------------------------------------
async function pageStatus() {
  const box = h('section', { 'aria-labelledby': 'h-status' });
  const draw = async () => {
    const s = await api('/status');
    const budget = 1536;
    box.replaceChildren(
      h('h2', { id: 'h-status' }, 'Status'),
      h('div', { class: 'grid-cards' }, s.processes.map((p) => h('article', {},
        h('header', {}, h('h3', {}, p.name), ' ', badge(p.running ? 'ok' : 'down', p.running ? 'up' : 'down')),
        h('p', {}, p.running ? `${p.ram_mb} MB RAM · ${p.cpu_pct}% CPU` : (p.name === 'windows-mcp' ? 'starts on demand' : 'not running')),
        p.pids.length ? h('p', { class: 'muted' }, `pid ${p.pids.join(', ')}${p.port ? ` · port ${p.port}` : ''}`) : null))),
      h('h3', {}, 'Memory'),
      h('div', { class: 'bars' }, h('span', {}, `${s.total_ram_mb} MB in use of the 1.5 GB budget`),
        h('div', { class: 'meter', role: 'img', 'aria-label': `${Math.round((100 * s.total_ram_mb) / budget)} percent of budget` },
          h('span', { style: `width:${Math.min(100, (100 * s.total_ram_mb) / budget)}%` }))),
      h('h3', {}, 'Today'),
      h('ul', {},
        h('li', {}, `${s.today.requests} requests (${counts(s.today.by_source)})`),
        h('li', {}, `Laya: ${s.today.auto} done on its own, ${s.today.asked} asked you first`),
        h('li', {}, `Approvals: ${counts(s.today.approvals)}`)),
      h('h3', {}, 'Linked to the hub'),
      h('p', { class: 'row' }, Object.entries(s.connected).map(([k, v]) => badge(v ? 'ok' : 'down', `${k}: ${v ? 'linked' : 'not linked'}`))),
      h('p', { class: 'muted' }, `Updated ${when(s.at)} · refreshes every 5 s`));
  };
  await draw();
  timer = setInterval(() => draw().catch(() => {}), 5000);
  return box;
}

async function pageChats() {
  const q = h('input', { type: 'search', placeholder: 'Search every chat', 'aria-label': 'Search chats' });
  const list = h('ul', { class: 'list', 'aria-label': 'Chats' });
  const view = h('div', { 'aria-live': 'polite' }, h('p', { class: 'muted' }, 'Pick a chat.'));
  const exportChat = async (id, fmt) => {
    const r = await api(`/chats/${enc(id)}/export?format=${fmt}`);
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_text) {
      const path = await window.pywebview.api.save_text(r.filename, r.text);
      if (path) toast(`Exported to ${path}`);
    } else {
      h('a', { href: URL.createObjectURL(new Blob([r.text], { type: 'text/plain' })), download: r.filename }).click();
    }
  };
  const open = async (id) => {
    let c;
    try { c = await api(`/chats/${enc(id)}`); } catch (e) { view.replaceChildren(fail(e)); return; }
    const title = h('input', { value: c.title, 'aria-label': 'Title to save it under' });
    const save = h('button', {}, 'Save');
    save.addEventListener('click', () => busy(save, async () => {
      const r = await api(`/chats/${enc(id)}/save`, { method: 'POST', body: { title: title.value } });
      toast(r.text); await load(); await open(id);
    }));
    view.replaceChildren(
      h('h3', {}, c.title),
      h('p', {}, c.saved ? badge('ok', 'saved: kept forever') : badge('user', 'deleted after 2 days unless saved')),
      h('div', { class: 'row' }, c.id.startsWith('hub/') ? title : null, save,
        h('button', { class: 'secondary', onclick: () => exportChat(id, 'md') }, 'Export .md'),
        h('button', { class: 'secondary', onclick: () => exportChat(id, 'json') }, 'Export .json')),
      c.turns.length ? c.turns.map((t) => h('div', { class: 'turn' }, h('span', { class: 'who' }, t.role),
        h('span', { class: 'muted' }, when(t.ts)), h('div', {}, t.text))) : h('p', { class: 'muted' }, 'Empty.'));
  };
  const load = async () => {
    const term = q.value.trim();
    const d = await api(`/chats${term ? `?q=${encodeURIComponent(term)}` : ''}`);
    const rows = term ? d.matches.map((m) => h('li', {}, h('button', { class: 'secondary outline', onclick: () => open(m.id) },
      h('strong', {}, m.id), h('br'), `${when(m.ts)} · ${m.role}: ${m.text}`)))
      : d.items.map((c) => h('li', {}, h('button', { class: 'secondary outline', onclick: () => open(c.id) },
        h('strong', {}, c.title), ' ', c.saved ? badge('ok', 'saved') : badge('unknown', `deleted ${left(c.expires)}`), h('br'),
        h('span', { class: 'muted' }, `${c.source} · ${c.turns} turns · ${when(c.last)}`), c.preview ? [h('br'), c.preview] : null)));
    list.replaceChildren(...(rows.length ? rows : [h('li', { class: 'muted' }, term ? 'No matches.' : 'No chats yet.')]));
  };
  q.addEventListener('input', debounce(() => load().catch((e) => list.replaceChildren(fail(e))), 300));
  await load();
  return h('section', {}, h('h2', {}, 'Chats'),
    h('p', { class: 'muted' }, 'Hub conversations and dictation history. Kept 2 days, unless saved (then forever).'),
    q, h('div', { class: 'split' }, list, view));
}

async function pageServices() {
  const grid = h('div', { class: 'grid-cards' });
  const note = h('p', { class: 'muted', role: 'status' });
  const card = (c) => {
    const out = h('output', { 'aria-live': 'polite' });
    const parts = [h('header', {}, h('h3', {}, c.title), ' ', badge(c.status)), h('p', {}, c.detail), h('p', { class: 'muted' }, c.help)];
    if (c.secret) {
      const input = h('input', { type: 'password', autocomplete: 'off', spellcheck: 'false', 'aria-label': `${c.title} token or key`,
        placeholder: c.secret_set ? 'saved (paste a new one to replace it)' : 'paste it here' });
      const save = h('button', {}, 'Save');
      save.addEventListener('click', () => busy(save, async () => {
        try {
          await api(`/secrets/${c.secret}`, { method: 'POST', body: { value: input.value } });
          input.value = '';
          toast('Saved to Windows Credential Manager.');
          await load(false);
        } catch (e) { out.textContent = e.message; }
      }));
      const remove = c.secret_set ? h('button', { class: 'secondary outline', onclick: async () => {
        if (!window.confirm(`Remove the ${c.title} secret from Credential Manager?`)) return;
        await api(`/secrets/${c.secret}`, { method: 'DELETE' });
        await load(false);
      } }, 'Remove') : null;
      parts.push(h('div', { class: 'row' }, input, save, remove));
    }
    if (c.id === 'telegram') {
      parts.push(h('p', { class: 'row' }, badge(c.paired ? 'ok' : 'user', c.paired ? 'paired' : 'not paired'),
        badge(c.bot_connected ? 'ok' : 'down', c.bot_connected ? 'bot running' : 'bot not running')));
    }
    parts.push(h('div', { class: 'row' }, c.actions.map((a) => {
      const b = h('button', { class: 'secondary' }, a.label);
      b.addEventListener('click', () => busy(b, async () => {
        try { const r = await api(`/services/${c.id}/${a.id}`, { method: 'POST' }); out.textContent = r.message; }
        catch (e) { out.textContent = e.message; }
      }));
      return b;
    })), out);
    return h('article', {}, parts);
  };
  const load = async (refresh) => {
    note.textContent = refresh ? 'Checking every service (can take up to a minute)…' : '';
    const d = await api(`/services${refresh ? '?refresh=1' : ''}`);
    note.textContent = `${d.error ? `${d.error} · ` : ''}checked ${when(d.checked_at)}`;
    grid.replaceChildren(...d.cards.map(card));
  };
  const recheck = h('button', {}, 'Re-check all');
  recheck.addEventListener('click', () => busy(recheck, () => load(true)));
  await load(false);
  return h('section', {}, h('h2', {}, 'Link services'),
    h('p', { class: 'muted' }, 'Keys and tokens go straight to Windows Credential Manager and are never shown again.'),
    h('div', { class: 'row' }, recheck, note), grid);
}

function answer(id, approved) {
  const item = live.get(id);
  if (!item || !ws || ws.readyState !== WebSocket.OPEN) { toast('Not linked to the hub; nothing was sent.', 'fail'); return; }
  ws.send(JSON.stringify({ id: newId(), type: 'approval_result', re: item.msg.id, approved, decided_by: 'ui', answer: 'button' }));
  live.delete(id);
  updateCount();
  toast(approved ? 'Approved.' : 'Denied.');
  if (current === 'approvals') show();
}

async function pageApprovals() {
  const d = await api('/approvals');
  const cols = [['created', 'When', (v) => when(v)], ['action', 'Action'], ['preview', 'What'], ['channel', 'Asked via'],
    ['status', 'Status', (v) => badge(v === 'approved' ? 'ok' : v === 'pending' ? 'user' : 'fail', v)], ['decided_by', 'By']];
  const here = [...live.entries()].map(([id, { record }]) => h('article', {},
    h('header', {}, h('h3', {}, record.preview || record.action)), h('p', { class: 'muted' }, `action: ${record.action}`),
    h('div', { class: 'row' }, h('button', { onclick: () => answer(id, true) }, 'Approve'),
      h('button', { class: 'secondary', onclick: () => answer(id, false) }, 'Deny'))));
  return h('section', {}, h('h2', {}, 'Approvals'),
    h('p', { class: 'muted' }, 'Critical actions always ask: voice first, then Telegram; this panel is asked when neither is there. No answer = denied.'),
    h('h3', {}, 'Asked here'), here.length ? h('div', { class: 'grid-cards' }, here) : h('p', { class: 'muted' }, 'Nothing is waiting in this panel.'),
    h('h3', {}, 'Pending'), table(d.pending, cols), h('h3', {}, 'Recent'), table(d.recent, cols));
}

async function pageLogs() {
  const pick = h('select', { 'aria-label': 'Log file' });
  const filter = h('input', { type: 'search', placeholder: 'Filter', 'aria-label': 'Filter lines' });
  const pre = h('pre', { class: 'log', tabindex: '0', 'aria-label': 'Log lines' });
  const load = async () => {
    const d = await api(`/logs?name=${encodeURIComponent(pick.value || 'vvhub')}&lines=400&q=${encodeURIComponent(filter.value.trim())}`);
    if (!pick.options.length) pick.replaceChildren(...d.names.map((n) => h('option', { value: n, selected: n === d.name }, n)));
    pre.textContent = d.lines.join('\n') || '(nothing)';
    pre.scrollTop = pre.scrollHeight;
  };
  pick.addEventListener('change', () => load().catch((e) => { pre.textContent = e.message; }));
  filter.addEventListener('input', debounce(() => load().catch(() => {}), 300));
  try { await load(); } catch (e) { pre.textContent = e.message; }
  timer = setInterval(() => load().catch(() => {}), 5000);
  return h('section', {}, h('h2', {}, 'Logs'), h('div', { class: 'row' }, pick, filter), pre);
}

async function pageReports() {
  const list = h('ul', { class: 'list', 'aria-label': 'Reports' });
  const view = h('div', {}, h('p', { class: 'muted' }, 'Reports are made at 08:00 and 20:00.'));
  const load = async () => {
    const d = await api('/reports');
    list.replaceChildren(...(d.items.length ? d.items.map((r) => h('li', {}, h('button', { class: 'secondary outline', onclick: async () => {
      const rep = await api(`/reports/${encodeURIComponent(r.name)}`);
      view.replaceChildren(h('iframe', { class: 'report', title: `Report ${r.name}`, sandbox: '', srcdoc: rep.html }));
    } }, r.name.replace('.html', ''), h('br'), h('span', { class: 'muted' }, when(r.modified))))) : [h('li', { class: 'muted' }, 'No reports yet.')]));
  };
  const now = h('button', {}, 'Make a report now');
  now.addEventListener('click', () => busy(now, async () => {
    const r = await api('/reports/now', { method: 'POST' });
    toast(r.message, r.ok ? '' : 'fail');
    await load();
  }));
  await load();
  return h('section', {}, h('h2', {}, 'Reports'), h('div', { class: 'row' }, now), h('div', { class: 'split' }, list, view));
}

async function pageMic() {
  const box = h('section', {}, h('h2', {}, 'Microphone'));
  let d;
  try { d = await api('/mics'); } catch (e) { box.append(fail(e)); return box; }
  const group = h('fieldset', {}, h('legend', {}, `In use: ${d.current || 'unknown'}`),
    d.devices.map((name, i) => h('label', { for: `mic-${i}` }, h('input', { type: 'radio', name: 'mic', id: `mic-${i}`, value: name, checked: name === d.current }), name)));
  const use = h('button', {}, 'Use this microphone');
  use.addEventListener('click', () => busy(use, async () => {
    const choice = box.querySelector('input[name=mic]:checked');
    if (!choice) return;
    try { const r = await api('/mics', { method: 'POST', body: { device: choice.value } }); toast(`Now using ${r.device} (until Voice Vibe restarts).`); show(); }
    catch (e) { toast(e.message, 'fail'); }
  }));
  box.append(h('p', { class: 'muted' }, 'Stereo Mix is never offered: it records silence. To keep a choice, set [audio].input_device in Settings.'), group, use);
  return box;
}

async function pageSettings() {
  const d = await api('/settings');
  const text = h('textarea', { class: 'toml', spellcheck: 'false', 'aria-label': 'config.toml' });
  text.value = d.text;
  const out = h('div', { 'aria-live': 'polite' });
  const report = (errors, warnings, ok) => out.replaceChildren(
    errors.length ? h('article', { class: 'fail', role: 'alert' }, h('strong', {}, 'Not saved:'), h('ul', {}, errors.map((e) => h('li', {}, e)))) : null,
    warnings.length ? h('article', { class: 'user' }, h('strong', {}, 'Warnings:'), h('ul', {}, warnings.map((w) => h('li', {}, w)))) : null,
    ok ? h('p', { class: 'ok' }, ok) : null);
  const check = h('button', { class: 'secondary' }, 'Check');
  check.addEventListener('click', () => busy(check, async () => {
    const r = await api('/settings/validate', { method: 'POST', body: { text: text.value } });
    report(r.errors, r.warnings, r.errors.length ? '' : 'Looks good.');
  }));
  const save = h('button', {}, 'Save');
  save.addEventListener('click', () => busy(save, async () => {
    try { const r = await api('/settings', { method: 'PUT', body: { text: text.value } }); report([], r.warnings, r.message); }
    catch (e) { report(e.message.split('\n'), [], ''); }
  }));
  const auto = h('input', { type: 'checkbox', role: 'switch', id: 'autostart' });
  auto.checked = (await api('/autostart')).enabled;
  auto.addEventListener('change', async () => {
    const r = await api('/autostart', { method: 'PUT', body: { enabled: auto.checked } });
    auto.checked = r.enabled;
    toast(r.enabled ? 'Voice Vibe and the hub start when you sign in.' : 'No autostart.');
  });
  report(d.errors, d.warnings, '');
  return h('section', {}, h('h2', {}, 'Settings'),
    h('label', { for: 'autostart' }, auto, 'Start Voice Vibe and the hub when I sign in to Windows'),
    h('h3', {}, 'config.toml'), h('p', { class: 'muted' }, `${d.path} · checked before saving; the old file is kept as config.toml.bak.`),
    text, h('div', { class: 'row' }, check, save), out);
}

async function pageOffice() {
  const mod = await import('/ui/static/office.js').catch(() => null);
  if (!mod) return h('section', {}, h('h2', {}, 'Office'), h('p', { class: 'muted' }, 'The office view is not installed.'));
  return mod.render({ api, h, when });
}

const PAGES = { status: pageStatus, chats: pageChats, services: pageServices, approvals: pageApprovals, logs: pageLogs,
  reports: pageReports, mic: pageMic, settings: pageSettings, office: pageOffice };

async function show() {
  const name = (location.hash.slice(1) || 'status').split('/')[0];
  current = PAGES[name] ? name : 'status';
  for (const a of document.querySelectorAll('#tabs a')) {
    if (a.getAttribute('href') === `#${current}`) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  clearInterval(timer);
  timer = null;
  const main = $('#main');
  const page = current;
  main.replaceChildren(h('p', { class: 'muted', 'aria-busy': 'true' }, 'Loading…'));
  let node;
  try { node = await PAGES[page](); } catch (e) { node = fail(e); }
  if (page === current) { main.replaceChildren(node); main.focus({ preventScroll: true }); }
}

function updateCount() {
  const el = $('#pending-count');
  el.hidden = live.size === 0;
  el.textContent = String(live.size);
  el.setAttribute('aria-label', `${live.size} waiting`);
}

function setLink(ok, why = '') {
  const el = $('#link');
  el.replaceChildren(badge(ok ? 'ok' : 'down', ok ? 'hub linked' : `hub not linked${why ? `: ${why}` : ''}`));
}

let backoff = 1000;
function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => ws.send(JSON.stringify({ id: newId(), type: 'hello', token: TOKEN, role: 'ui', version: 'ui-1' }));
  ws.onmessage = (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    if (m.type === 'welcome') { backoff = 1000; setLink(true); }
    else if (m.type === 'ping') ws.send(JSON.stringify({ id: newId(), type: 'pong', re: m.id }));
    else if (m.type === 'notify') toast(`${m.title || 'Voice Vibe'}: ${m.text || ''}`);
    else if (m.type === 'approval_request') {
      const record = m.approval && typeof m.approval === 'object' ? m.approval : m;
      const id = String(record.id || m.id);
      live.set(id, { msg: m, record });
      updateCount();
      toast(`Approval needed: ${record.preview || record.action}`, 'user');
      setTimeout(() => { if (live.delete(id)) { updateCount(); if (current === 'approvals') show(); } }, 1000 * (m.timeout || 300));
      if (current === 'approvals') show();
    }
  };
  ws.onclose = (ev) => {
    setLink(false, ev.code === 4401 ? 'token rejected' : '');
    live.clear();
    updateCount();
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 30000);
  };
}

function getToken() {
  return new Promise((resolve) => {
    const ready = async () => { try { resolve(await window.pywebview.api.token()); } catch { resolve(null); } };
    if (window.pywebview && window.pywebview.api && window.pywebview.api.token) ready();
    else {
      window.addEventListener('pywebviewready', ready, { once: true });
      setTimeout(() => resolve(null), 6000);
    }
  });
}

async function boot() {
  TOKEN = await getToken();
  if (!TOKEN) {
    $('#boot').textContent = "Open this panel from Voice Vibe's tray icon (Control panel): it needs the hub's token.";
    setLink(false, 'no token');
    return;
  }
  window.addEventListener('hashchange', show);
  connect();
  show();
}

boot();
