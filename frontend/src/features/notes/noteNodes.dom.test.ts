/** @vitest-environment jsdom */
import { Editor } from "@tiptap/react";
import { afterEach, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { noteExtensions } from "./editorExtensions";
const editors: Editor[] = [];
afterEach(() => {
  editors.splice(0).forEach((e) => e.destroy());
  document.body.replaceChildren();
  vi.restoreAllMocks();
});
function setup(markdown: string, editable = true) {
  const element = document.createElement("div");
  document.body.append(element);
  const editor = new Editor({
    element,
    extensions: noteExtensions(!editable),
    content: markdown,
    contentType: "markdown",
    editable,
  });
  editors.push(editor);
  return { editor, element };
}
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
  const language = element.querySelector("select")!;
  expect(language.value).toBe("js");
  language.value = "typescript";
  language.dispatchEvent(new Event("change", { bubbles: true }));
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
  expect(editor.getHTML()).not.toContain("<select");
  expect(editor.getMarkdown()).not.toContain("已复制");
  const reopened = setup(editor.getMarkdown(), false);
  expect(reopened.element.querySelector("select")!.hidden).toBe(true);
  expect(
    reopened.element.querySelector(".note-code-language-label")!.textContent,
  ).toBe("TypeScript");
  expect(reopened.editor.getJSON()).toEqual(editor.getJSON());
});
it("preserves unknown code languages as plain text without breaking editing", () => {
  const { editor, element } = setup("```custom-lang\n<not-an-element>\n```");
  expect(element.querySelector("select")!.value).toBe("custom-lang");
  expect(element.querySelector("pre")!.textContent).toBe("<not-an-element>");
  expect(editor.getMarkdown()).toContain("```custom-lang");
});

it("moves the model selection from an image into code before immediate typing", () => {
  const { editor, element } = setup(
    "![image](https://example.com/a.png)\n\n```js\nconst x = 1;\n```",
  );
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
