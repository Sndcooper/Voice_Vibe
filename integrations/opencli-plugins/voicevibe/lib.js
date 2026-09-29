// Voice Vibe OpenCLI plugin — shared logic (no OpenCLI imports, so it can be
// unit-tested with a fake `page`). The command files next to this one wire
// these functions into OpenCLI's registry with `cli({...})`.
//
// Builds on jackwener/opencli (Apache-2.0): same page API, error classes and
// the fail-closed write pattern of its built-in `twitter post` /
// `linkedin safe-send` adapters (verify composer text, require fresh success
// evidence, never retry an unconfirmed submit).
//
// Selectors are best effort for the 2026 LinkedIn / Instagram / GitHub web
// UIs and have NOT been exercised against the live sites yet.

export const LINKEDIN_FEED = 'https://www.linkedin.com/feed/';
export const LINKEDIN_COMPOSE = 'https://www.linkedin.com/feed/?shareActive=true';
export const LINKEDIN_MAX = 3000;
const POLL_MS = 500;

export function normalizeText(s) {
  return String(s ?? '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
}

export function validatePostText(text, max) {
  const value = String(text ?? '').trim();
  if (!value) return 'Post text is empty.';
  if (value.length > max) return `Post text is ${value.length} characters (max ${max}).`;
  return null;
}

function unwrap(value) {
  // Browser Bridge may wrap evaluate() results as { result: ... } or { value: ... }.
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    if ('ok' in value || 'rows' in value || 'status' in value) return value;
    if ('result' in value) return value.result;
    if ('value' in value) return value.value;
  }
  return value;
}

async function evalJson(page, script) {
  return unwrap(await page.evaluate(script));
}

// ---------------------------------------------------------------- LinkedIn

const COMPOSER_JS = `(() => {
  const visible = (el) => !!el && (el.offsetParent !== null || el.getClientRects().length > 0);
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"]')).filter(visible);
  const scope = dialogs.find(d => d.querySelector('[contenteditable="true"]')) || null;
  if (!scope) {
    const opener = Array.from(document.querySelectorAll('button, [role="button"]'))
      .find(b => visible(b) && /start a post/i.test(b.textContent || b.getAttribute('aria-label') || ''));
    if (opener) { opener.click(); return { ok: false, opened: true }; }
    return { ok: false, message: 'LinkedIn post composer not found.' };
  }
  const box = Array.from(scope.querySelectorAll('.ql-editor[contenteditable="true"], [role="textbox"][contenteditable="true"], [contenteditable="true"]')).find(visible);
  if (!box) return { ok: false, message: 'LinkedIn composer has no text box.' };
  box.focus();
  return { ok: true };
})()`;

function composerTextJs(expected) {
  return `(() => {
    const norm = s => String(s || '').replace(/\\u00a0/g, ' ').replace(/\\s+/g, ' ').trim();
    const box = document.querySelector('[role="dialog"] [contenteditable="true"]');
    const actual = box ? (box.innerText || box.textContent || '') : '';
    return { ok: !!box && norm(actual) === norm(${JSON.stringify(expected)}), actual };
  })()`;
}

function insertFallbackJs(text) {
  return `(() => {
    const box = document.querySelector('[role="dialog"] [contenteditable="true"]');
    if (!box) return { ok: false, message: 'LinkedIn composer has no text box.' };
    box.focus();
    if (!document.execCommand('insertText', false, ${JSON.stringify(text)})) {
      const dt = new DataTransfer();
      dt.setData('text/plain', ${JSON.stringify(text)});
      box.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
    }
    return { ok: true };
  })()`;
}

const CLICK_POST_JS = `(() => {
  const visible = (el) => !!el && (el.offsetParent !== null || el.getClientRects().length > 0);
  for (const t of document.querySelectorAll('[role="alert"], .artdeco-toast-item')) {
    if (visible(t)) t.setAttribute('data-vv-before-submit', '1');
  }
  const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find(visible);
  if (!dialog) return { ok: false, message: 'Composer closed before posting.' };
  const btn = Array.from(dialog.querySelectorAll('button'))
    .find(b => visible(b) && /^post$/i.test((b.textContent || '').trim()) && !b.disabled && b.getAttribute('aria-disabled') !== 'true');
  if (!btn) return { ok: false, message: 'LinkedIn Post button is disabled or missing.' };
  btn.click();
  return { ok: true };
})()`;

const POST_RESULT_JS = `(() => {
  const visible = (el) => !!el && (el.offsetParent !== null || el.getClientRects().length > 0);
  const toasts = Array.from(document.querySelectorAll('[role="alert"], .artdeco-toast-item'))
    .filter(t => visible(t) && !t.hasAttribute('data-vv-before-submit'));
  const good = toasts.find(t => /post successful|view post|your post (was|has been) (shared|posted)/i.test(t.textContent || ''));
  if (good) {
    const link = good.querySelector('a[href*="/feed/update/"]');
    return { ok: true, url: link ? link.href : '' };
  }
  const bad = toasts.find(t => /couldn.t|failed|error|try again|something went wrong/i.test(t.textContent || ''));
  if (bad) return { ok: false, message: (bad.textContent || 'LinkedIn rejected the post.').trim() };
  return { ok: false, pending: true };
})()`;

async function hasLinkedinSession(page) {
  if (typeof page.getCookies !== 'function') return true;
  const cookies = await page.getCookies({ url: 'https://www.linkedin.com' });
  return cookies.some(c => c.name === 'li_at' && c.value);
}

async function openComposer(page, errors) {
  await page.goto(LINKEDIN_COMPOSE, { waitUntil: 'load', settleMs: 2500 });
  for (let i = 0; i < 20; i++) {
    const state = await evalJson(page, COMPOSER_JS);
    if (state?.ok) return;
    if (state?.message && !state.opened && i > 6) {
      throw new errors.CommandExecutionError(state.message, 'Open LinkedIn in Edge and check you are logged in.');
    }
    await page.wait(POLL_MS / 1000);
  }
  throw new errors.CommandExecutionError('LinkedIn post composer did not open.', 'Nothing was posted.');
}

async function typeIntoComposer(page, text) {
  for (const insert of [page.insertText?.bind(page), page.nativeType?.bind(page)].filter(Boolean)) {
    try {
      await insert(text);
      const check = await evalJson(page, composerTextJs(text));
      if (check?.ok) return true;
    } catch {
      // Older Browser Bridge builds lack this insertion path; try the next one.
    }
  }
  await evalJson(page, insertFallbackJs(text));
  await page.wait(0.5);
  return !!(await evalJson(page, composerTextJs(text)))?.ok;
}

/**
 * Publish a LinkedIn text post. Without `send` it only proves the composer
 * opens (nothing is typed or published). With `send` it types, verifies the
 * exact text, clicks Post once and waits for LinkedIn's success toast.
 */
export async function linkedinPost(page, kwargs, errors) {
  const text = String(kwargs.text ?? '').trim();
  const invalid = validatePostText(text, LINKEDIN_MAX);
  if (invalid) throw new errors.ArgumentError(invalid);
  if (!page) throw new errors.CommandExecutionError('Browser session required for linkedin-post');
  if (!(await hasLinkedinSession(page))) {
    throw new errors.AuthRequiredError('linkedin.com', 'LinkedIn li_at cookie missing');
  }
  await openComposer(page, errors);
  if (!kwargs.send) {
    if (typeof page.pressKey === 'function') await page.pressKey('Escape');
    return [{ status: 'ready', message: 'Composer opened; nothing posted (pass --send to publish).', text, url: '' }];
  }
  if (!(await typeIntoComposer(page, text))) {
    throw new errors.CommandExecutionError('Could not verify the post text in the composer.', 'Nothing was posted.');
  }
  await page.wait(1);
  const click = await evalJson(page, CLICK_POST_JS);
  if (!click?.ok) {
    throw new errors.CommandExecutionError(click?.message || 'Could not click Post.', 'Nothing was posted.');
  }
  const polls = Math.ceil((Number(kwargs.timeout) || 20) * 1000 / POLL_MS);
  for (let i = 0; i < polls; i++) {
    await page.wait(POLL_MS / 1000);
    const result = await evalJson(page, POST_RESULT_JS);
    if (result?.ok) return [{ status: 'posted', message: 'LinkedIn post published.', text, url: result.url || '' }];
    if (result && !result.pending) {
      throw new errors.CommandExecutionError(result.message || 'LinkedIn rejected the post.', 'Check the composer in Edge.');
    }
  }
  // Not confirmed is not "failed": the post may be live. Never let a caller
  // retry blindly (the same double-post trap OpenCLI's twitter post avoids).
  throw new errors.TimeoutError('linkedin post', Number(kwargs.timeout) || 20,
    'Post submitted but not confirmed. Check your LinkedIn activity before retrying.');
}

// --------------------------------------------------------------- Instagram

export const IG_APP_ID = '936619743392459';

function igTime(ts) {
  const n = Number(ts);
  return Number.isFinite(n) && n > 0 ? new Date(n * 1000).toISOString() : '';
}

/** Map Instagram's activity-inbox payload to rows. Pure; exported for tests. */
export function mapInstagramInbox(payload, limit) {
  if (!payload || typeof payload !== 'object') throw new Error('Instagram activity returned no JSON object');
  const fresh = Array.isArray(payload.new_stories) ? payload.new_stories : [];
  const old = Array.isArray(payload.old_stories) ? payload.old_stories : [];
  if (!Array.isArray(payload.new_stories) && !Array.isArray(payload.old_stories)) {
    throw new Error('Instagram activity payload has no stories');
  }
  const rows = [];
  for (const [list, unread] of [[fresh, true], [old, false]]) {
    for (const story of list) {
      const args = story?.args || {};
      const media = Array.isArray(args.media) && args.media[0] ? args.media[0] : {};
      rows.push({
        rank: rows.length + 1,
        type: String(story?.story_type ?? story?.type ?? ''),
        user: String(args.profile_name || ''),
        text: normalizeText(args.rich_text || args.text || ''),
        time: igTime(args.timestamp),
        unread,
        media_id: String(media.id || ''),
        key: String(story?.pk || args.tuuid || `${args.profile_id || ''}:${args.timestamp || ''}:${story?.story_type ?? ''}`),
      });
      if (rows.length >= limit) return rows;
    }
  }
  return rows;
}

function igInboxJs() {
  return `(async () => {
    const headers = { 'X-IG-App-ID': ${JSON.stringify(IG_APP_ID)}, 'X-Requested-With': 'XMLHttpRequest' };
    let r = await fetch('/api/v1/news/inbox/', { credentials: 'include', headers });
    if (r.status === 405) {
      const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
      r = await fetch('/api/v1/news/inbox/', { method: 'POST', credentials: 'include',
        headers: { ...headers, 'X-CSRFToken': csrf } });
    }
    if (r.status === 401 || r.status === 403) return { status: 'auth', code: r.status };
    if (!r.ok) return { status: 'http', code: r.status };
    try { return { status: 'ok', body: await r.json() }; } catch { return { status: 'json' }; }
  })()`;
}

export async function instagramNotifications(page, kwargs, errors) {
  const limit = Math.max(1, Math.min(100, Number(kwargs.limit) || 20));
  if (!page) throw new errors.CommandExecutionError('Browser session required for instagram-notifications');
  await page.goto('https://www.instagram.com/', { waitUntil: 'load', settleMs: 1500 });
  const res = await evalJson(page, igInboxJs());
  if (res?.status === 'auth') throw new errors.AuthRequiredError('instagram.com');
  if (res?.status !== 'ok') {
    throw new errors.CommandExecutionError(`Instagram activity request failed (${res?.status} ${res?.code ?? ''})`.trim());
  }
  let rows;
  try {
    rows = mapInstagramInbox(res.body, limit);
  } catch (err) {
    throw new errors.CommandExecutionError(String(err?.message || err));
  }
  if (!rows.length) throw new errors.EmptyResultError('voicevibe instagram-notifications', 'No recent activity.');
  return rows;
}

// ------------------------------------------------------------------ GitHub

const GITHUB_NOTIFICATIONS_JS = `(() => {
  if (/\\/login/.test(location.pathname)) return { status: 'auth' };
  const items = Array.from(document.querySelectorAll('.notifications-list-item, [data-notification-id]'));
  const rows = items.map((li) => {
    const link = li.querySelector('a.notification-list-item-link, a[href*="/pull/"], a[href*="/issues/"], a[href*="/discussions/"], a[href*="/commit/"]');
    const title = li.querySelector('.markdown-title, [data-testid="notification-title"]');
    const repo = li.querySelector('.f6 .text-bold, p.m-0.f6, [data-testid="repository-name"]');
    const reason = li.querySelector('.color-fg-muted .f6, [data-testid="notification-reason"]');
    return {
      id: li.getAttribute('data-notification-id') || '',
      title: (title ? title.textContent : (link ? link.textContent : '')).replace(/\\s+/g, ' ').trim(),
      repo: (repo ? repo.textContent : '').replace(/\\s+/g, ' ').trim(),
      reason: (reason ? reason.textContent : '').replace(/\\s+/g, ' ').trim(),
      url: link ? link.href : '',
      unread: li.classList.contains('notification-unread'),
    };
  }).filter(r => r.title || r.url);
  return { status: 'ok', rows };
})()`;

export async function githubNotifications(page, kwargs, errors) {
  const limit = Math.max(1, Math.min(50, Number(kwargs.limit) || 20));
  if (!page) throw new errors.CommandExecutionError('Browser session required for github-notifications');
  await page.goto('https://github.com/notifications', { waitUntil: 'load', settleMs: 1500 });
  const res = await evalJson(page, GITHUB_NOTIFICATIONS_JS);
  if (res?.status === 'auth') throw new errors.AuthRequiredError('github.com');
  const rows = Array.isArray(res?.rows) ? res.rows : null;
  if (!rows) throw new errors.CommandExecutionError('GitHub notifications page returned no rows payload');
  if (!rows.length) throw new errors.EmptyResultError('voicevibe github-notifications', 'Inbox is empty.');
  return rows.slice(0, limit).map((r, i) => ({ rank: i + 1, ...r }));
}
