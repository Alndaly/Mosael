import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { compileMDX } from "next-mdx-remote/rsc";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { registerSourceAliases } from "./source-aliases.mjs";

//: 文档正文(`content/docs/<语言>/<栏目>/*.mdx`)按文档页那一套编译、再渲染一遍:编不过、或者用了没注册的组件,就红。
//:
//: 此前 `website test` 不碰这些文件,只有 `website build` 预渲染时才编它们 —— f5db6125f 在英文版 ComfyUI 指南里写了一句
//: “From <workflow>”,MDX 把 `<workflow>` 当成一个没闭合的 JSX 标签,test 绿、build 红,main 的 CI 红了两个小时。
registerSourceAliases();

const { LOCALES } = await import("../src/i18n/config.ts");
const { listDocs, readDoc } = await import("../src/lib/docs.ts");
const { mdxOptions } = await import("../src/lib/mdx-options.ts");

//: 正文里能写的组件就是 `mdxComponents()` 交出去的那几个(src/components/mdx.tsx)。那是 TSX,这里 import 不了,
//: 就从源码里把名字读出来、每个换成一个空壳 —— 要查的是「用到的组件都注册过」,不是组件自己画得对不对。
const COMPONENTS_SOURCE = fs.readFileSync(path.resolve(import.meta.dirname, "..", "src", "components", "mdx.tsx"), "utf8");
const returned = COMPONENTS_SOURCE.match(/export function mdxComponents\([^)]*\) \{\s*return \{([\s\S]*?)\n {2}\};\n\}/);
assert.ok(returned, "src/components/mdx.tsx 里 mdxComponents 的写法变了,这条测试读不出注册了哪些组件 —— 跟着改");
const REGISTERED = [...returned[1].matchAll(/^ {2}([A-Z]\w*)\s*[,:]/gm)].map((match) => match[1]);
const STUBS = Object.fromEntries(REGISTERED.map((name) => [name, ({ children }) => createElement("div", null, children)]));

test("从 mdx.tsx 读出了注册的组件", () => {
  //: 读不出来的话,下面那条会把每个组件都当成没注册 —— 先确认读法还对得上
  for (const name of ["Aside", "Steps", "Shot", "DownloadChoice"]) assert.ok(REGISTERED.includes(name), `${name} 不在 ${REGISTERED}`);
});

test("每篇文档(两种语言)都按文档页那一套编得过、渲染得出来", async () => {
  const failures = [];
  let rendered = 0;
  for (const locale of LOCALES) {
    for (const meta of listDocs(locale)) {
      const doc = readDoc(locale, meta.section, meta.name);
      const where = `content/docs/${locale}/${meta.section}/${meta.name}.mdx`;
      try {
        const { content } = await compileMDX({ source: doc.body, components: STUBS, options: { mdxOptions } });
        renderToStaticMarkup(content);
        rendered += 1;
      } catch (error) {
        //: 编译错的第一行是固定的抬头,原因(哪一行、哪个标签)在下一行;渲染错(没注册的组件)就一行
        const reason = String(error?.message ?? error).split("\n").filter((line) => line.trim()).slice(0, 2).join(" ");
        failures.push(`${where}: ${reason}`);
      }
    }
  }
  assert.deepEqual(
    failures,
    [],
    `这些文档在官网上编不过或渲染不出来(正文里裸的 <…> 写成反引号、或去掉尖括号;组件要先在 mdx.tsx 里注册):\n${failures.join("\n")}`,
  );
  assert.ok(rendered > 0, "一篇文档都没编到 —— 读文档的路子变了,这条测试也得跟着改");
});
