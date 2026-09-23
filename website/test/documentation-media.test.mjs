import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const media = path.resolve('public/media');
const docs = path.resolve('content/docs');
const version = JSON.parse(fs.readFileSync('../package.json', 'utf8')).version;
const manifest = JSON.parse(fs.readFileSync(path.join(media, 'capture-manifest.json'), 'utf8'));
const files = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory() ? files(path.join(dir, e.name)) : [path.join(dir, e.name)]);

test('every current screenshot and recording has an intact live-capture provenance entry', () => {
  assert.equal(manifest.documentedVersion ?? manifest.version, version);
  for (const kind of ['screens', 'gifs', 'videos', 'homepage']) {
    for (const file of files(path.join(media, kind))) {
      const relative = path.relative(media, file);
      const record = manifest.captures[relative];
      assert.ok(record, `Untracked or stale media: ${relative}`);
      assert.equal(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'), record.sha256, relative);
    }
  }
});

test('all scenes have light/dark and Chinese/English recordings', () => {
  for (const scene of ['scenes', 'notes', 'annotations', 'home', 'media-preview', 'timeline-edit', 'subtitle-dub', 'ai-studio', 'workflows', 'boards', 'plugins', 'publishing', 'scheduler', 'providers', 'appearance', 'login']) {
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
    assert.equal(body.match(/^version: (.+)$/m)?.[1], version, relative);
    for (const match of body.matchAll(/\/media\/(?:screens|gifs|videos)\/[^\s"')]+/g)) {
      const src = match[0];
      assert.ok(fs.existsSync(path.join('public', src)), `${relative}: ${src}`);
      assert.equal(src.includes('/en/'), locale === 'en', `${relative}: wrong image language`);
      const last = src.lastIndexOf('/');
      assert.ok(fs.existsSync(path.join('public', src.slice(0,last), 'dark',src.slice(last+1))), `${src}: missing dark theme`);
    }
  }
});


test('MDX document links resolve after the renderer adds the current locale', () => {
  for (const file of files(docs).filter(file => file.endsWith('.mdx'))) {
    const locale = path.relative(docs, file).split(path.sep)[0];
    const body = fs.readFileSync(file, 'utf8');
    for (const [, href] of body.matchAll(/\]\((\/[^)]+)\)/g)) {
      assert.doesNotMatch(href, /^\/(en|zh)\//, `${file}: renderer already adds locale: ${href}`);
      if (!href.startsWith('/docs/')) continue;
      const target = href.split(/[?#]/)[0].slice('/docs/'.length);
      assert.ok(fs.existsSync(path.join(docs, locale, target + '.mdx')), `${file}: ${href}`);
    }
  }
});

/**
 * 版本号在官网上**只有一个真值**：`package.json` 的 version。
 *
 * `docs/RELEASING.md` 写着「版本号要改的地方不止 package.json。官网的测试会逐项核对，
 * 漏一处就红在 '1.3.0' !== '1.3.1'」—— 而实测它只核对了 5 处中的 2 处
 * （`capture-manifest` 的 documentedVersion、各篇 mdx frontmatter 的 version）。
 *
 * **这句话比什么都不写更危险**：它的作用正是让发版的人不用逐个去查。漏掉下载页正文的
 * 版本号，CI 会绿，而用户在官网上读到的是「1.4.2 已正式发布」——而当前是 1.4.3。
 *
 * 所以这一条**扫整棵文档树**，不维护一份「哪些文件带版本号」的清单：清单会在下一次
 * 有人新写一篇带版本号的文档时失效，而那正是上一版失守的方式（棘轮的扫描面停在写它那天）。
 * 判据是地址无关的 —— 一行里出现 `X.Y.Z`，它就必须是当前版本。
 */
const VERSION_SHAPED = /(?<![.\d])(\d+\.\d+\.\d+)(?![.\d])/g;

/** 这份文档树里所有会被读者当成「当前版本」的地方。 */
function versionBearingFiles() {
  const files = [path.resolve('README.md')];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.mdx')) files.push(full);
    }
  };
  walk(path.resolve('content/docs'));
  return files;
}

test('每一处写在正文里的版本号都等于当前版本', () => {
  const files = versionBearingFiles();
  // 扫描面本身也要有人看着：走空目录的话下面那句 deepEqual 天然为真。
  assert.ok(files.length > 20, `只扫到 ${files.length} 个文件，文档树的位置变了吗`);

  const stale = [];
  for (const file of files) {
    const relative = path.relative(path.resolve('.'), file);
    let fenced = false;
    fs.readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, index) => {
        if (line.trimStart().startsWith('```')) {
          fenced = !fenced;
          return;
        }
        // 围栏里是**别的东西**的数据（插件清单的 "version": "0.1.0"、示例 JSON），
        // 不是读者读成「当前发布版」的那句话。frontmatter 的 version 由上面那条核。
        if (fenced || line.trim().startsWith('version:')) return;

        const found = [...line.matchAll(VERSION_SHAPED)].map((m) => m[1]);
        if (found.length === 0) return;

        // **判据：这一行提到当前版本了吗。**
        //
        // 讲历史的段落会列一长串版本（「本文档适用于 1.4.3……1.4.1 改过的界面……」），
        // 那是有意留着的 —— 同一行里有当前版本，旧的就是上下文。反过来，一行里**只有**
        // 旧版本，那就是发版时漏改的那一处。
        //
        // 第一版按措辞豁免（匹配「尚未补录」之类），而英文那段用的是另一套说法，于是误报 ——
        // 按措辞判的规则，换一种说法就失效。
        if (found.includes(version)) return;
        for (const one of found) {
          stale.push(`${relative}:${index + 1} 写着 ${one}，而当前是 ${version}`);
        }
      });
  }
  assert.deepEqual(stale, [], `官网正文里的版本号过期了：\n  ${stale.join('\n  ')}`);
});

test('这一版的中英亮点在 release-copy 里存在', () => {
  const copy = fs.readFileSync(path.resolve('src/lib/release-copy.ts'), 'utf8');
  assert.ok(
    copy.includes(`"v${version}"`),
    `release-copy.ts 里没有 v${version} 这一条 —— 官网首页的亮点会是上一版的`,
  );
});
