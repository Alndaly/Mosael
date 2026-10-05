import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { compileMDX } from "next-mdx-remote/rsc";

//: 插件详情页的 README 是**当 MDX 编译的**:正文里一个裸的 `<节点标题>` 就是一个没闭合的 JSX 标签,
//: `next build` 预渲染那一页时整站构建失败 —— 而此前这里的测试只看 README 在不在、语言对不对,一路全绿。
//: 这里每个插件、每种语言的 README 都按详情页那一套(同一个 pluginDocSource、同一份 mdxOptions、同一个 compileMDX)
//: 编一遍,编不过就红。
const SRC = path.resolve(import.meta.dirname, "..", "src");
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith("@/")) {
      return nextResolve(pathToFileURL(path.join(SRC, `${specifier.slice(2)}.ts`)).href, context);
    }
    return nextResolve(specifier, context);
  },
});

const { LOCALES } = await import("../src/i18n/config.ts");
const { README_FILE, listPlugins, readPluginDoc } = await import("../src/lib/registry.ts");
const { mdxOptions } = await import("../src/lib/mdx-options.ts");
const { pluginDocSource } = await import("../src/lib/plugin-doc.ts");

test("每个插件的 README(两种语言)都按详情页那一套编得过 MDX", async () => {
  const failures = [];
  let compiled = 0;
  for (const locale of LOCALES) {
    for (const plugin of listPlugins(locale)) {
      const raw = readPluginDoc(plugin.slug, locale);
      if (!raw) continue;
      try {
        await compileMDX({ source: pluginDocSource(raw, plugin.source), options: { mdxOptions } });
        compiled += 1;
      } catch (error) {
        //: next-mdx-remote 的报错第一行是固定的抬头,原因(哪一行、哪个标签)在下一行
        const reason = String(error?.message ?? error).split("\n").filter((line) => line.trim()).slice(0, 2).join(" ");
        failures.push(`${plugin.source}/${README_FILE[locale]}: ${reason}`);
      }
    }
  }
  assert.deepEqual(failures, [], `这些 README 在官网插件页上编不过(裸的 <…> 写成反引号或去掉尖括号):\n${failures.join("\n")}`);
  assert.ok(compiled > 0, "一份 README 都没编到 —— 读 README 的路子变了,这条测试也得跟着改");
});
