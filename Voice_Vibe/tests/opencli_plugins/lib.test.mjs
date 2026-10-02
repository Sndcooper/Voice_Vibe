// node --test for the Voice Vibe OpenCLI plugin logic, with a fake `page`.
// Run by tests/test_opencli_plugins.py; never touches a browser or network.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  linkedinPost, instagramNotifications, githubNotifications, mapInstagramInbox, validatePostText,
} from '../../integrations/opencli-plugins/voicevibe/lib.js';

class CliError extends Error { constructor(m) { super(m); this.name = this.constructor.name; } }
const errors = {
  ArgumentError: class ArgumentError extends CliError {},
  CommandExecutionError: class CommandExecutionError extends CliError {},
  AuthRequiredError: class AuthRequiredError extends CliError { constructor(d, m) { super(m || d); } },
  EmptyResultError: class EmptyResultError extends CliError {},
  TimeoutError: class TimeoutError extends CliError { constructor(l) { super(`${l} timed out`); } },
};

function fakePage(rules, { cookies = [{ name: 'li_at', value: 'x' }] } = {}) {
  const log = [];
  return {
    log,
    async goto(url) { log.push(['goto', url]); },
    async wait() {},
    async pressKey(k) { log.push(['key', k]); },
    async getCookies() { return cookies; },
    async insertText(t) { log.push(['insertText', t]); },
    async evaluate(script) {
      for (const [needle, reply] of rules) {
        if (script.includes(needle)) {
          log.push(['eval', needle]);
          return typeof reply === 'function' ? reply() : reply;
        }
      }
      throw new Error('unexpected script');
    },
  };
}

const composerOk = ['start a post', { ok: true }];

test('linkedin-post without --send never types or clicks Post', async () => {
  const page = fakePage([composerOk]);
  const rows = await linkedinPost(page, { text: 'Hello' }, errors);
  assert.equal(rows[0].status, 'ready');
  assert.ok(!page.log.some(e => e[0] === 'insertText'));
  assert.ok(!page.log.some(e => e[1] === "data-vv-before-submit', '1'"));
});

test('linkedin-post --send types, verifies, clicks once, needs a fresh success toast', async () => {
  let clicks = 0;
  const page = fakePage([
    composerOk,
    ['const actual = box', { ok: true }],
    ["data-vv-before-submit', '1'", () => { clicks += 1; return { ok: true }; }],
    ['post successful', { ok: true, url: 'https://www.linkedin.com/feed/update/urn:li:activity:1/' }],
  ]);
  const rows = await linkedinPost(page, { text: 'Hello world', send: true }, errors);
  assert.equal(rows[0].status, 'posted');
  assert.equal(clicks, 1);
  assert.deepEqual(page.log.find(e => e[0] === 'insertText'), ['insertText', 'Hello world']);
});

test('linkedin-post unconfirmed submit is a timeout, not a retryable failure', async () => {
  let clicks = 0;
  const page = fakePage([
    composerOk,
    ['const actual = box', { ok: true }],
    ["data-vv-before-submit', '1'", () => { clicks += 1; return { ok: true }; }],
    ['post successful', { ok: false, pending: true }],
  ]);
  await assert.rejects(linkedinPost(page, { text: 'Hi', send: true, timeout: 1 }, errors), errors.TimeoutError);
  assert.equal(clicks, 1);
});

test('linkedin-post stops before clicking when the text cannot be verified', async () => {
  let clicked = false;
  const page = fakePage([
    composerOk,
    ['const actual = box', { ok: false, actual: 'Hel' }],
    ['execCommand', { ok: true }],
    ["data-vv-before-submit', '1'", () => { clicked = true; return { ok: true }; }],
  ]);
  await assert.rejects(linkedinPost(page, { text: 'Hello', send: true }, errors), errors.CommandExecutionError);
  assert.equal(clicked, false);
});

test('linkedin-post requires login and valid text', async () => {
  await assert.rejects(linkedinPost(fakePage([composerOk], { cookies: [] }), { text: 'x', send: true }, errors),
    errors.AuthRequiredError);
  await assert.rejects(linkedinPost(fakePage([composerOk]), { text: '   ' }, errors), errors.ArgumentError);
  assert.match(validatePostText('a'.repeat(3001), 3000), /3001/);
});

test('instagram inbox maps new and old stories', () => {
  const rows = mapInstagramInbox({
    new_stories: [{ story_type: 60, pk: 'a1', args: { profile_name: 'amy', text: 'amy liked your post.', timestamp: 1700000000, media: [{ id: 'm1' }] } }],
    old_stories: [{ story_type: 101, args: { profile_name: 'bob', rich_text: 'bob commented: nice', timestamp: 1690000000 } }],
  }, 10);
  assert.equal(rows.length, 2);
  assert.deepEqual([rows[0].user, rows[0].unread, rows[0].media_id, rows[0].key], ['amy', true, 'm1', 'a1']);
  assert.equal(rows[1].unread, false);
  assert.equal(rows[0].time, '2023-11-14T22:13:20.000Z');
  assert.throws(() => mapInstagramInbox({ status: 'ok' }, 10));
});

test('instagram notifications: auth wall and empty feed are typed', async () => {
  await assert.rejects(instagramNotifications(fakePage([['news/inbox', { status: 'auth', code: 401 }]]), {}, errors),
    errors.AuthRequiredError);
  await assert.rejects(instagramNotifications(fakePage([['news/inbox', { status: 'ok', body: { new_stories: [], old_stories: [] } }]]), {}, errors),
    errors.EmptyResultError);
});

test('github notifications rows are ranked and limited', async () => {
  const page = fakePage([['notifications-list-item', { status: 'ok', rows: [
    { title: 'Fix bug', repo: 'a/b', url: 'https://github.com/a/b/pull/1', unread: true, id: '1', reason: 'review' },
    { title: 'Other', repo: 'a/c', url: 'https://github.com/a/c/issues/2', unread: false, id: '2', reason: 'mention' },
  ] }]]);
  const rows = await githubNotifications(page, { limit: 1 }, errors);
  assert.deepEqual(rows, [{ rank: 1, title: 'Fix bug', repo: 'a/b', url: 'https://github.com/a/b/pull/1', unread: true, id: '1', reason: 'review' }]);
  await assert.rejects(githubNotifications(fakePage([['notifications-list-item', { status: 'auth' }]]), {}, errors),
    errors.AuthRequiredError);
});
