import assert from "node:assert/strict";
import fs from "node:fs";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

//: registry.ts 用 `@/` 别名 import(Next 的 tsconfig paths)。node 自己不认它 —— 在这里把
//: `@/x` 指到 src/x.ts,测试读的就是页面构建时用的那一份,不另抄一份逻辑。
const SRC = path.resolve(import.meta.dirname, "..", "src");
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      return nextResolve(pathToFileURL(path.join(SRC, `${specifier.slice(2)}.ts`)).href, context);
    }
    return nextResolve(specifier, context);
  },
});

const { README_FILE, findPlugin, listPlugins, readPluginDoc } = await import("../src/lib/registry.ts");

const PLUGINS = path.resolve(import.meta.dirname, "..", "..", "plugins");
const idsIn = (dir) =>
  fs
    .readdirSync(path.join(PLUGINS, dir))
    .map((slug) => path.join(PLUGINS, dir, slug, "mosael.plugin.json"))
    .filter((file) => fs.existsSync(file))
    .map((file) => JSON.parse(fs.readFileSync(file, "utf8")).id);

test("插件页列出示例插件和随应用内置的插件,一个不漏", () => {
  const listed = listPlugins("zh").map((plugin) => plugin.id).sort();
  assert.deepEqual(listed, [...idsIn("examples"), ...idsIn("bundled")].sort());
});

test("随应用内置的 ComfyUI 找得到,标了内置,源码指向 plugins/bundled", () => {
  const comfy = findPlugin("comfyui", "zh");
  assert.ok(comfy, "官网插件页里找不到 ComfyUI");
  assert.equal(comfy.id, "dev.mosael.comfyui");
  assert.equal(comfy.bundled, true);
  assert.equal(comfy.source, "plugins/bundled/comfyui");
  //: README 从它自己的目录读,不是去 examples 下找一个不存在的。
  assert.ok(readPluginDoc("comfyui", "zh"), "内置插件的 README 没读到");
});

test("示例插件不标内置,源码指向 plugins/examples", () => {
  const examples = listPlugins("en").filter((plugin) => !plugin.bundled);
  assert.ok(examples.length >= 3);
  for (const plugin of examples) assert.equal(plugin.source, `plugins/examples/${plugin.slug}`);
});

//: ---- 详情页的正文按语言分两份 ----
//: 此前每个插件只有一份中英段落交替的 README,两种语言的详情页渲染的都是它:中文页开头一段英文,
//: 英文页几乎整篇中文。现在 `README.md` 是英文、`README.zh-CN.md` 是中文(和仓库根目录同一套约定)。

const CJK = /[\u3400-\u9fff\uff00-\uffef\u3000-\u303f]/;

/** 正文里的「文字」:去掉代码块、行内代码、链接地址和 HTML 注释 —— 那些不是给人读的句子。 */
function proseLines(markdown) {
  let fenced = false;
  const lines = [];
  for (const line of markdown.replace(/<!--[\s\S]*?-->/g, "").split("\n")) {
    if (/^\s*(```|~~~)/.test(line)) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    lines.push(line.replace(/`[^`]*`/g, "").replace(/\]\([^)]*\)/g, "]").replace(/https?:\/\/\S+/g, ""));
  }
  return lines;
}

const documented = () => listPlugins("en").filter((plugin) => readPluginDoc(plugin.slug, "en") || readPluginDoc(plugin.slug, "zh"));

test("有说明的插件中英两份都有 —— 缺一种就会在那种语言的页面上没有正文", () => {
  assert.ok(documented().length >= 5, "一份 README 都没读到 —— 扫描本身坏了");
  for (const plugin of documented()) {
    for (const locale of ["en", "zh"]) {
      assert.ok(readPluginDoc(plugin.slug, locale), `${plugin.source}/${README_FILE[locale]} 不存在`);
    }
  }
});

test("英文 README 的正文里没有中文", () => {
  for (const plugin of documented()) {
    const offenders = proseLines(readPluginDoc(plugin.slug, "en")).filter((line) => CJK.test(line));
    assert.deepEqual(offenders, [], `${plugin.source}/README.md 里混着中文(要举界面上的中文原话就放进行内代码)`);
  }
});

test("中文 README 里不夹整句英文", () => {
  for (const plugin of documented()) {
    const offenders = proseLines(readPluginDoc(plugin.slug, "zh")).filter(
      (line) => !CJK.test(line) && (line.match(/[A-Za-z]{2,}/g) ?? []).length >= 6,
    );
    assert.deepEqual(offenders, [], `${plugin.source}/README.zh-CN.md 里有整句英文`);
  }
});

test("两种语言的详情页读的是各自那一份", () => {
  for (const plugin of documented()) {
    assert.notEqual(readPluginDoc(plugin.slug, "en"), readPluginDoc(plugin.slug, "zh"), plugin.slug);
  }
});
