import test from 'node:test';
import assert from 'node:assert/strict';
import { publishedReleases, releaseHighlights } from '../src/lib/release-data.ts';

const release = (tag, date, extra = {}) => ({ tag_name: tag, name: tag, published_at: date, draft: false, prerelease: false, body: '', ...extra });

test('only published releases appear, sorted by publication date', () => {
  const result = publishedReleases([
    release('v1.0.0-beta2', '2026-09-04T17:18:47Z', { prerelease: true }),
    release('v1.0.0-beta3', null),
    release('v1.0.0-beta5', '2026-09-07T00:00:00Z', { draft: true }),
    release('v1.0.0-beta4', '2026-09-06T09:06:25Z', { prerelease: true }),
    release('v0.27.6', '2026-09-02T13:07:07Z'),
  ]);
  assert.deepEqual(result.map(r => r.tag), ['v1.0.0-beta4', 'v1.0.0-beta2', 'v0.27.6']);
  assert.deepEqual(result.map(r => r.prerelease), [true, true, false]);
});

test('malformed remote data is rejected and external URLs are never trusted', () => {
  assert.deepEqual(publishedReleases({ error: 'rate limited' }), []);
  assert.deepEqual(publishedReleases([null, {}, release('../bad', '2026-09-06'), release('v1.0.0', 'invalid')]), []);
  const result = publishedReleases([release('v1.0.0', '2026-09-06', { html_url: 'javascript:alert(1)' })]);
  assert.equal(result[0].url, 'https://github.com/Alndaly/Mosael/releases/tag/v1.0.0');
});

test('beta tags stay marked pre-release and duplicate releases do not produce duplicate entries', () => {
  const item = release('v1.0.0-beta4', '2026-09-06');
  const result = publishedReleases([item, item]);
  assert.equal(result.length, 1);
  assert.equal(result[0].prerelease, true);
});

test('release excerpts are bounded readable text with no markdown evaluation', () => {
  assert.deepEqual(releaseHighlights('## Fixes\n\n- **Import** [files](https://example.com).\n- Keep `data` safe.'), ['Import files.', 'Keep data safe.']);
  assert.equal(releaseHighlights(Array(20).fill('a'.repeat(400)).join('\n')).length, 5);
  assert.ok(releaseHighlights('a'.repeat(400))[0].length <= 260);
  assert.deepEqual(releaseHighlights(''), []);
});
