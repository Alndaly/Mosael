import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const media = path.resolve('public/media');
const docs = path.resolve('content/docs');
const manifest = JSON.parse(fs.readFileSync(path.join(media, 'capture-manifest.json'), 'utf8'));
const files = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? files(path.join(dir, e.name)) : [path.join(dir, e.name)]);

test('every current screenshot and recording has an intact live-capture provenance entry', () => {
  for (const kind of ['screens', 'gifs', 'videos']) {
    for (const file of files(path.join(media, kind))) {
      const relative = path.relative(media, file);
      const record = manifest.captures[relative];
      assert.ok(record, `Untracked or stale media: ${relative}`);
      assert.equal(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), record.sha256, relative);
    }
  }
});

test('all scenes have light/dark and Chinese/English recordings', () => {
  for (const scene of ['home', 'media-preview', 'timeline-edit', 'subtitle-dub', 'ai-studio', 'workflows', 'boards', 'plugins', 'publishing', 'scheduler', 'providers', 'appearance', 'login']) {
    for (const locale of ['zh', 'en']) for (const theme of ['light', 'dark']) {
      const directory = `${locale === 'en' ? 'en/' : ''}${theme === 'dark' ? 'dark/' : ''}`;
      for (const [kind, extension] of [['gifs', 'gif'], ['videos', 'mp4']]) {
        assert.ok(manifest.captures[`${kind}/${directory}${scene}.${extension}`], `${scene}/${locale}/${theme}/${kind}`);
      }
    }
  }
});

test('localized docs reference existing media, use the correct language, and have matching translations', () => {
  for (const file of files(docs)) {
    if (!file.endsWith('.mdx')) continue;
    const relative = path.relative(docs, file);
    const locale = relative.split(path.sep)[0];
    assert.ok(fs.existsSync(path.join(docs, relative.replace(/^(zh|en)/, locale === 'zh' ? 'en' : 'zh'))), relative);
    const body = fs.readFileSync(file, 'utf8');
    assert.match(body, /version: 1\.0\.0-beta5/);
    for (const match of body.matchAll(/\/media\/(?:screens|gifs|videos)\/[^\s"')]+/g)) {
      const src = match[0];
      assert.ok(fs.existsSync(path.join('public', src)), `${relative}: ${src}`);
      assert.equal(src.includes('/en/'), locale === 'en', `${relative}: wrong image language`);
      const last = src.lastIndexOf('/');
      assert.ok(fs.existsSync(path.join('public', src.slice(0,last), 'dark',src.slice(last+1))), `${src}: missing dark theme`);
    }
  }
});
