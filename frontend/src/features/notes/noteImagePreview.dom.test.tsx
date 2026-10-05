/** @vitest-environment jsdom */
import React from "react";
import { Editor, EditorContent } from "@tiptap/react";
import { afterEach, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

import { IMAGE_PREVIEW_EVENT, type ImagePreviewRequest } from "@/components/app/image-preview-request";
import { noteExtensions } from "./editorExtensions";

/**
 * 笔记正文里的图看大图。
 *
 * 编辑时点图的意思是「选中它去改链接」(那张小表单弹出来),所以看大图是压在图上的另一颗按钮;只读时(版本记录)
 * 点图本身也开。两处开的都是**这一篇的全部图**,按正文里的先后。画板上的笔记卡片不给按钮(那里整块不接指针)。
 */

const editors: Editor[] = [];
const requests: ImagePreviewRequest[] = [];
const onRequest = (event: Event) => requests.push((event as CustomEvent<ImagePreviewRequest>).detail);
document.addEventListener(IMAGE_PREVIEW_EVENT, onRequest);

afterEach(() => {
  editors.splice(0).forEach((editor) => editor.destroy());
  document.body.replaceChildren();
  requests.length = 0;
  vi.restoreAllMocks();
});

//: 开头是一段字:文档若以图片开头,初始选区会落在那张图上(选中即弹改链接的表单),和这里要测的无关。
const MARKDOWN = [
  "开头一段字",
  "",
  "![封面](https://example.com/cover.png)",
  "",
  "中间一段字",
  "",
  "![](https://example.com/detail.png)",
  "",
  "![坏的](javascript:alert(1))",
].join("\n");

function setup({ editable = true, previewImages = true } = {}) {
  const editor = new Editor({
    extensions: noteExtensions(!editable, "zh-CN", { previewImages }),
    content: MARKDOWN,
    contentType: "markdown",
    editable,
  });
  editors.push(editor);
  const { container } = render(React.createElement(EditorContent, { editor }));
  return { editor, element: container };
}

const zoomButtons = (element: HTMLElement) => [...element.querySelectorAll<HTMLButtonElement>('button[aria-label="看大图"]')];

it("每张图上一颗「看大图」;点它开这一篇的全部图,从这一张开始,不弹改链接的表单", () => {
  const { element } = setup();
  const buttons = zoomButtons(element);
  expect(buttons).toHaveLength(3);
  //: 真点一下先有按下:编辑器若接了这一下,图就被选中、改链接的表单弹出来。
  buttons[1].dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
  buttons[1].click();
  expect(requests).toEqual([
    {
      src: "https://example.com/detail.png",
      title: "笔记图片 2",
      gallery: [
        { src: "https://example.com/cover.png", title: "封面" },
        { src: "https://example.com/detail.png", title: "笔记图片 2" },
      ],
    },
  ]);
  expect([...element.querySelectorAll("form")].every((form) => form.hidden), "看大图不等于选中它去改").toBe(true);
});

it("编辑时点图本身仍然是选中它去改链接,不开大图", () => {
  const { element } = setup();
  (element.querySelector("img") as HTMLElement).click();
  expect(element.querySelector("form")!.hidden).toBe(false);
  expect(requests).toEqual([]);
});

it("只读时点图就开大图(没有别的意思)", () => {
  const { element } = setup({ editable: false });
  (element.querySelector("img") as HTMLElement).click();
  expect(requests[0]?.src).toBe("https://example.com/cover.png");
  expect(requests[0]?.gallery).toHaveLength(2);
});

it("画板卡片那种用法(不开看大图)不放按钮,点图也不开", () => {
  const { element } = setup({ editable: false, previewImages: false });
  expect(zoomButtons(element)).toEqual([]);
  (element.querySelector("img") as HTMLElement).click();
  expect(requests).toEqual([]);
});

it("显示不出来的图连同它的「看大图」一起收起", () => {
  const { element } = setup();
  const frames = [...element.querySelectorAll<HTMLElement>(".note-image-frame")];
  expect(frames.map((frame) => frame.hidden)).toEqual([false, false, true]);
  frames[0].querySelector("img")!.dispatchEvent(new Event("error"));
  expect(frames[0].hidden).toBe(true);
});
