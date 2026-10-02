import { cli, Strategy } from '@jackwener/opencli/registry';
import * as errors from '@jackwener/opencli/errors';
import { linkedinPost } from './lib.js';

cli({
  site: 'voicevibe',
  name: 'linkedin-post',
  access: 'write',
  description: 'Publish a LinkedIn text post (dry-run unless --send)',
  example: 'opencli voicevibe linkedin-post --send -- "Post text"',
  domain: 'www.linkedin.com',
  strategy: Strategy.UI,
  browser: true,
  args: [
    { name: 'text', type: 'string', required: true, positional: true, help: 'Post text (max 3000 chars)' },
    { name: 'send', type: 'boolean', default: false, help: 'Actually publish; without it only the composer is checked' },
    { name: 'timeout', type: 'int', default: 20, help: 'Seconds to wait for LinkedIn to confirm the post' },
  ],
  columns: ['status', 'message', 'text', 'url'],
  func: (page, kwargs) => linkedinPost(page, kwargs, errors),
});
