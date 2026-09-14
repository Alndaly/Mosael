/** @vitest-environment jsdom */
import React from "react";
import { Editor, EditorContent } from "@tiptap/react";
import { afterEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { noteExtensions } from "./editorExtensions";
const editors: Editor[] = [];
afterEach(() => {
  editors.splice(0).forEach((e) => e.destroy());
  document.body.replaceChildren();
  vi.restoreAllMocks();
});
/**
 * 代码块的节点视图是 React 的(要用仓库自己的下拉),而 React 节点视图只有挂在 React 根上
 * 才会渲染 —— 裸 `new Editor({element})` 没有那个根,节点视图整块不出现。所以这里走
 * `EditorContent`,和应用里一样。
 */
function setup(markdown: string, editable = true) {
  const editor = new Editor({
    extensions: noteExtensions(!editable),
    content: markdown,
    contentType: "markdown",
    editable,
  });
  editors.push(editor);
  const { container } = render(React.createElement(EditorContent, { editor }));
  return { editor, element: container };
}

/** React 节点视图是下一轮 React 渲染才填进去的,碰它之前得等它挂上。 */
const codeMounted = (element: HTMLElement) =>
  waitFor(() => expect(element.querySelector(".note-code-block")).not.toBeNull());
it("edits an image beside the selection, preserves its title and supports undo and Markdown reload", () => {
  const { editor, element } = setup(
    '![Before](https://example.com/old.png "Caption")\n\nAfter',
  );
  (element.querySelector("img") as HTMLElement).click();
  const form = element.querySelector("form")!;
  expect(form.hidden).toBe(false);
  const src = form.querySelector('[aria-label="图片链接"]') as HTMLInputElement;
  const alt = form.querySelector('[aria-label="替代文字"]') as HTMLInputElement;
  src.value = "mosael-asset:new123";
  alt.value = "New description";
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  expect(editor.getMarkdown()).toContain(
    '![New description](mosael-asset:new123 "Caption")',
  );
  expect(editor.getHTML()).not.toContain("<form");
  expect(editor.getHTML()).not.toContain("token=");
  expect(form.hidden).toBe(true);
  const reopened = setup(editor.getMarkdown());
  expect(reopened.editor.getJSON()).toEqual(editor.getJSON());
  editor.commands.undo();
  expect(editor.getMarkdown()).toContain("https://example.com/old.png");
});
it("rejects invalid image URLs, cancels drafts, and hides editing controls in reading mode", () => {
  const { editor, element } = setup("![Original](https://example.com/a.png)");
  (element.querySelector("img") as HTMLElement).click();
  const form = element.querySelector("form")!,
    src = form.querySelector("input")!;
  src.value = "javascript:alert(1)";
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  expect(src.validationMessage).not.toBe("");
  expect(editor.getMarkdown()).toContain("https://example.com/a.png");
  form.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
  );
  expect(form.hidden).toBe(true);
  const reader = setup(editor.getMarkdown(), false);
  (reader.element.querySelector("img") as HTMLElement).click();
  expect(reader.element.querySelector("form")!.hidden).toBe(true);
});
it("highlights editable code, changes language without changing text, and copies only code", async () => {
  const { editor, element } = setup(
    '```js\nconst greeting = "你好";\nconsole.log(greeting);\n```',
  );
  await codeMounted(element);
  await waitFor(
    () =>
      expect(
        element.querySelectorAll(".note-code-token").length,
      ).toBeGreaterThan(3),
    { timeout: 10000 },
  );
  expect(
    element.querySelector(".note-code-token")!.getAttribute("style"),
  ).toContain("--note-code-dark:");
  expect(
    element.querySelector(".note-code-token")!.getAttribute("style"),
  ).toMatch(/--note-code-light:\s*#[0-9A-Fa-f]+/);
  const language = element.querySelector(".note-code-language") as HTMLElement;
  expect(language.textContent).toBe("JavaScript");
  await userEvent.click(language);
  await userEvent.click(await screen.findByRole("option", { name: "TypeScript" }));
  expect(editor.getMarkdown()).toContain("```typescript");
  const copy = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: copy },
  });
  (element.querySelector('[aria-label="复制代码"]') as HTMLElement).click();
  await waitFor(() =>
    expect(element.querySelector('[role="status"]')!.textContent).toBe(
      "已复制",
    ),
  );
  expect(copy).toHaveBeenCalledWith(
    'const greeting = "你好";\nconsole.log(greeting);',
  );
  editor.commands.insertContentAt(1, "// Updated\n");
  await waitFor(() =>
    expect(element.querySelector("pre")!.textContent).toContain("// Updated"),
  );
  expect(editor.getMarkdown()).not.toContain("已复制");
  const reopened = setup(editor.getMarkdown(), false);
  await codeMounted(reopened.element);
  // 只读时不给选择器,只给一行标签。
  expect(reopened.element.querySelector(".note-code-language")).toBeNull();
  expect(
    reopened.element.querySelector(".note-code-language-label")!.textContent,
  ).toBe("TypeScript");
  expect(reopened.editor.getJSON()).toEqual(editor.getJSON());
});
it("preserves unknown code languages as plain text without breaking editing", async () => {
  const { editor, element } = setup("```custom-lang\n<not-an-element>\n```");
  await codeMounted(element);
  expect((element.querySelector(".note-code-language") as HTMLElement).textContent).toBe("custom-lang");
  expect(element.querySelector("pre")!.textContent).toBe("<not-an-element>");
  expect(editor.getMarkdown()).toContain("```custom-lang");
});

it("moves the model selection from an image into code before immediate typing", async () => {
  const { editor, element } = setup(
    "![image](https://example.com/a.png)\n\n```js\nconst x = 1;\n```",
  );
  await codeMounted(element);
  (element.querySelector("img") as HTMLElement).click();
  expect(editor.state.selection.toJSON().type).toBe("node");
  vi.spyOn(editor.view, "posAtCoords").mockReturnValue({ pos: 2, inside: 1 });
  element
    .querySelector("pre")!
    .dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
  editor.commands.insertContent("// comment\n");
  expect(editor.getMarkdown()).toContain("![image](https://example.com/a.png)");
  expect(editor.state.doc.child(1).textContent).toContain("// comment");
});

it("代码块里写 Markdown 时,围栏要比内容里最长那串反引号更长", () => {
  // 上游写死三个反引号,于是一段讲 Markdown 的代码块会把自己拆掉:内层那行提前收尾,
  // 剩下的内容掉到正文里。而且再存一次形状还会继续变 —— 两遍不收敛,所以这里验到第二遍。
  const source = "````md\n```js\ncode\n```\n````";
  const { editor } = setup(source);
  const once = editor.getMarkdown().trim();
  expect(once).toBe(source);
  expect(setup(once).editor.getMarkdown().trim()).toBe(source);
});

it("普通代码块仍然是三个反引号", () => {
  // 围栏只在需要时才加长 —— 不能因为修了套娃就让每个代码块都变成四个反引号。
  const { editor } = setup("```ts\nconst a = 1;\n```");
  expect(editor.getMarkdown().trim()).toBe("```ts\nconst a = 1;\n```");
});
