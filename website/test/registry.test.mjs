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

const { findPlugin, listPlugins, readPluginDoc } = await import("../src/lib/registry.ts");

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
  assert.ok(readPluginDoc("comfyui"), "内置插件的 README 没读到");
});

test("示例插件不标内置,源码指向 plugins/examples", () => {
  const examples = listPlugins("en").filter((plugin) => !plugin.bundled);
  assert.ok(examples.length >= 3);
  for (const plugin of examples) assert.equal(plugin.source, `plugins/examples/${plugin.slug}`);
});
