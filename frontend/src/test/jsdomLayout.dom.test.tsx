/** @vitest-environment jsdom */
/**
 * setup.ts 给 jsdom 补的 Range 版面接口。
 *
 * TipTap 的 focus() 在下一帧把选区滚进视野,一路调到 range.getClientRects。jsdom 没有它,
 * 这一帧要是落在用例结束之后,就成了一条 unhandled error,整轮测试判失败(CI 上时红时绿)。
 * 这里同步地调那条路上真正取版面的那一步(coordsAtPos),不靠帧时机。验证能否删:去掉 setup.ts 里那两行跑本文件。
 */
import { Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { afterEach, expect, it } from "vitest";

let editor: Editor | null = null;
afterEach(() => editor?.destroy());

it("编辑器取选区坐标(滚进视野要用)不会因 jsdom 缺版面接口而抛错", () => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  editor = new Editor({ element: host, extensions: [StarterKit], content: "<p>一行字</p>" });
  expect(() => editor!.view.coordsAtPos(2)).not.toThrow();
  host.remove();
});
