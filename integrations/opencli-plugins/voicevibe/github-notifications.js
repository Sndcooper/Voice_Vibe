import { cli, Strategy } from '@jackwener/opencli/registry';
import * as errors from '@jackwener/opencli/errors';
import { githubNotifications } from './lib.js';

// Web fallback only: the GitHub skill (WS4) uses `gh api notifications` first.
cli({
  site: 'voicevibe',
  name: 'github-notifications',
  access: 'read',
  description: 'List GitHub web notifications (fallback when gh CLI is unavailable)',
  example: 'opencli voicevibe github-notifications --limit 10 -f json',
  domain: 'github.com',
  strategy: Strategy.COOKIE,
  browser: true,
  args: [
    { name: 'limit', type: 'int', default: 20, help: 'Max rows (1-50)' },
  ],
  columns: ['rank', 'title', 'repo', 'reason', 'url', 'unread', 'id'],
  func: (page, kwargs) => githubNotifications(page, kwargs, errors),
});
