/**
 * 读页面(存成笔记的那一半):整页交回渲染后的 HTML(脚本样式剥掉、页面本身不动),或只交选中的文字。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

import { READ_PAGE_SCRIPT } from "./pageReadCore";

const FIXTURES = join(import.meta.dirname, "fixtures", "page-tools");
const ORIGIN = "http://127.0.0.1:47011";

/** 静态测试页装进 jsdom。jsdom 不加载媒体、不实现 EME、不解码图片 —— 这几样由用例按页面声明补上。 */
function open(name: string): JSDOM {
  return new JSDOM(readFileSync(join(FIXTURES, name), "utf8"), {
    url: `${ORIGIN}/${name}`,
    runScripts: "outside-only",
  });
}

describe("读正文(静态测试页)", () => {
  const read = (dom: JSDOM, mode: "article" | "selection") =>
    dom.window.eval(`${READ_PAGE_SCRIPT}(${JSON.stringify(mode)}, 4000000, 200000)`) as { html: string; selection: string };

  it("整页:交回渲染后的 HTML,脚本和样式剥掉,页面本身不动", () => {
    const dom = open("drm.html");
    const { html, selection } = read(dom, "article");
    expect(html).toContain("受 DRM 保护的视频");
    expect(html).not.toContain("<script");
    expect(selection).toBe("");
    expect(dom.window.document.querySelectorAll("script")).toHaveLength(1);
  });

  it("选中的文字:只交那一段", () => {
    const dom = open("none.html");
    const paragraph = dom.window.document.querySelector("article p")!;
    const range = dom.window.document.createRange();
    range.selectNodeContents(paragraph);
    dom.window.getSelection()!.addRange(range);
    expect(read(dom, "selection")).toEqual({ selection: "第一段正文:页面工具应该能把这段读成笔记。", html: "" });
  });
});
