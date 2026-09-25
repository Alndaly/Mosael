import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';

import { InlineMarkdown, parseInline, toPlainText } from '../src/lib/inline-markdown.ts';
import { releaseCopy } from '../src/lib/release-copy.ts';
import { HIGHLIGHT_MAX_LENGTH, publishedReleases, releaseHighlights } from '../src/lib/release-data.ts';

const html = (text, props = {}) => renderToStaticMarkup(createElement(InlineMarkdown, { text, ...props }));
/** 纯文本里不该剩下的记号:成对的 `**`、反引号、`[文字](地址)`。 */
const LEFTOVER = /\*\*|`|\]\(|~~/;

test('行内记号各自落成对应的元素', () => {
  assert.equal(html('把**公网直链**交回'), '把<strong class="font-semibold text-foreground">公网直链</strong>交回');
  assert.match(html('一个 `export default` 组件'), /<code[^>]*>export default<\/code>/);
  assert.equal(html('*斜体* 和 _也是_'), '<em>斜体</em> 和 <em>也是</em>');
  assert.equal(html('~~旧的~~'), '<del>旧的</del>');
  assert.match(html('见 [文档](https://example.com/docs)'), /<a href="https:\/\/example.com\/docs"[^>]*target="_blank"[^>]*>文档<\/a>/);
  assert.match(html('<https://example.com>'), /<a href="https:\/\/example.com"/);
  assert.equal(html('第一段\n\n第二段'), '第一段<br/>第二段');
  assert.equal(html('同一段\n接着写'), '同一段 接着写');
  assert.equal(html('***都有***'), '<strong class="font-semibold text-foreground"><em>都有</em></strong>');
});

test('不是记号的星号、下划线、反引号原样留着', () => {
  assert.deepEqual(parseInline('run_host_code 和 snake_case_name'), [{ type: 'text', value: 'run_host_code 和 snake_case_name' }]);
  assert.equal(toPlainText('2 * 3 * 4'), '2 * 3 * 4');
  assert.equal(toPlainText('没收尾的 **粗体'), '没收尾的 **粗体');
  assert.equal(toPlainText('单个 ` 反引号'), '单个 ` 反引号');
  assert.equal(toPlainText('转义 \\*不是斜体\\*'), '转义 *不是斜体*');
  // 代码里的记号不再解析:`a*b*c` 是代码,不是 a<em>b</em>c。
  assert.equal(html('`a*b*c`').includes('<em>'), false);
  assert.equal(toPlainText('`{{…}}` 和 `run_host_code`'), '{{…}} 和 run_host_code');
});

test('危险链接只留文字,可以关掉链接', () => {
  assert.equal(html('[点我](javascript:alert(1))'), '点我');
  assert.match(html('[维基](https://en.wikipedia.org/wiki/Foo_(bar))'), /href="https:\/\/en.wikipedia.org\/wiki\/Foo_\(bar\)"/);
  assert.equal(html('[文档](https://example.com)', { links: false }), '文档');
  assert.equal(toPlainText('![截图](a.png) 与 [文档](https://example.com)'), '截图 与 文档');
});

test('截断按看得见的字数,不会截出半个记号', () => {
  const long = `**${'字'.repeat(300)}** 结尾`;
  const out = html(long, { maxLength: 20 });
  assert.equal(out, `<strong class="font-semibold text-foreground">${'字'.repeat(20)}…</strong>`);
  assert.equal(toPlainText(long, 10), `${'字'.repeat(9)}…`);
});

// —— 站上真实的数据,过一遍页面用的同一套函数 ——

test('更新日志:每条要点渲染后记号都变成了元素,纯文本里一个不剩', () => {
  let strong = 0;
  for (const [tag, copy] of Object.entries(releaseCopy)) {
    for (const line of [...copy.zh, ...copy.en]) {
      const rendered = html(line, { maxLength: HIGHLIGHT_MAX_LENGTH });
      const text = rendered.replace(/<code[^>]*>[\s\S]*?<\/code>/g, '').replace(/<[^>]+>/g, '');
      assert.doesNotMatch(text, LEFTOVER, `${tag}: ${line}`);
      assert.doesNotMatch(toPlainText(line), /\*\*|\]\(/, `${tag}: ${line}`);
      if (rendered.includes('<strong')) strong += 1;
    }
  }
  assert.ok(strong > 10, '发布要点里的粗体应当渲染成 <strong>');
});

test('更新日志:GitHub 发布说明的摘录保留行内格式交给渲染', () => {
  const snapshot = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, '../content/releases.json'), 'utf8'));
  for (const release of publishedReleases(snapshot.releases)) {
    for (const line of releaseHighlights(release.body)) {
      const text = html(line, { maxLength: HIGHLIGHT_MAX_LENGTH }).replace(/<code[^>]*>[\s\S]*?<\/code>/g, '').replace(/<[^>]+>/g, '');
      assert.doesNotMatch(text, /\*\*|\]\(/, `${release.tag}: ${line}`);
    }
  }
});

const ROOT = path.join(import.meta.dirname, '../..');
const localized = (value) => (typeof value === 'string' ? [value] : value ? Object.values(value) : []);

test('插件:清单里的技能描述和工具说明,纯文本与渲染两条路都没有残留记号', () => {
  const dir = path.join(ROOT, 'plugins/examples');
  let strong = 0;
  for (const name of fs.readdirSync(dir)) {
    const file = path.join(dir, name, 'mosael.plugin.json');
    if (!fs.existsSync(file)) continue;
    const manifest = JSON.parse(fs.readFileSync(file, 'utf8'));
    const texts = [
      ...localized(manifest.skills?.[0]?.description),
      ...(manifest.tools?.declare ?? []).flatMap((tool) => localized(tool.description)),
    ];
    for (const text of texts) {
      assert.doesNotMatch(toPlainText(text), LEFTOVER, `${name}: ${text}`);
      const rendered = html(text);
      assert.doesNotMatch(rendered.replace(/<code[^>]*>[\s\S]*?<\/code>/g, '').replace(/<[^>]+>/g, ''), LEFTOVER, `${name}: ${text}`);
      if (rendered.includes('<strong')) strong += 1;
    }
  }
  assert.ok(strong > 0, '对象存储插件的描述里有粗体,应当渲染成 <strong>');
});

test('工作流目录:简介、步骤、准备项同样过得去', () => {
  const catalog = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, '../public/workflows/catalog.json'), 'utf8'));
  for (const entry of catalog) {
    for (const text of [...localized(entry.summary), ...Object.values(entry.stages).flat(), ...Object.values(entry.requires).flat()]) {
      assert.doesNotMatch(toPlainText(text), LEFTOVER, `${entry.id}: ${text}`);
    }
  }
});

// —— 源码棘轮:数据里的字只能经这两个出口上页面 ——

function sources(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? sources(full) : /\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

const SRC = path.join(import.meta.dirname, '../src');
const rel = (file) => path.relative(SRC, file);

test('页面不直接把数据里的说明文字塞进 JSX 或 meta', () => {
  // `summary` / `description` 是数据字段;直接 `{x.summary}` 当 JSX 子节点就是把 markdown 当纯文本露出来
  // (`summary={x.summary}` 交给组件的 prop 不算,组件里再过这一关)。
  const direct = /(?<![=$\w])\{\s*(?!t\.)[\w?.]+\.(?:summary|description)\s*\}/;
  const meta = /description:\s*(?!toPlainText\()(?!t\.)[\w?.]+\.(?:summary|description)\b/;
  // 更新要点、工作流步骤、准备项在 map 里叫 line / stage / item,详情页头的简介 prop 叫 summary,同样是数据。
  const listed = /(?<![=$\w])\{\s*(?:line|stage|item|summary)\s*\}/;
  // 首页轮播的说明来自 i18n/messages.ts 里手写的文案,不是数据。
  const allowed = new Set(['components/home-showcase.tsx']);
  const offenders = sources(SRC)
    .filter((file) => file.endsWith('.tsx') && !allowed.has(rel(file)))
    .filter((file) => {
      const text = fs.readFileSync(file, 'utf8');
      return direct.test(text) || meta.test(text) || listed.test(text);
    })
    .map(rel);
  assert.deepEqual(offenders, []);
});

test('没有第二套剥 markdown 的正则', () => {
  // 剥 `**` 或把 `*_\`` 一把删掉的正则,只允许出现在 inline-markdown.ts 里。
  const adhoc = /\/[^/\n]*(?:\\\*\\\*|\[[^\]\n]*\*[^\]\n]*`[^\]\n]*\]|\[[^\]\n]*`[^\]\n]*\*[^\]\n]*\])[^/\n]*\/[gimsuy]*/;
  const offenders = sources(SRC)
    .filter((file) => rel(file) !== 'lib/inline-markdown.ts')
    .filter((file) => adhoc.test(fs.readFileSync(file, 'utf8')))
    .map(rel);
  assert.deepEqual(offenders, []);
});
