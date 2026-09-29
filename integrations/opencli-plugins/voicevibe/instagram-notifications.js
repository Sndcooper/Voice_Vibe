import { cli, Strategy } from '@jackwener/opencli/registry';
import * as errors from '@jackwener/opencli/errors';
import { instagramNotifications } from './lib.js';

cli({
  site: 'voicevibe',
  name: 'instagram-notifications',
  access: 'read',
  description: 'List recent Instagram activity (likes, comments, follows, mentions)',
  example: 'opencli voicevibe instagram-notifications --limit 10 -f json',
  domain: 'www.instagram.com',
  strategy: Strategy.COOKIE,
  browser: true,
  args: [
    { name: 'limit', type: 'int', default: 20, help: 'Max rows (1-100)' },
  ],
  columns: ['rank', 'type', 'user', 'text', 'time', 'unread', 'media_id', 'key'],
  func: (page, kwargs) => instagramNotifications(page, kwargs, errors),
});
