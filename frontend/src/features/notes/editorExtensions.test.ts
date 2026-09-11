/** @vitest-environment jsdom */
import { Editor } from "@tiptap/react";
import { describe, expect, it } from "vitest";
import { noteExtensions, noteImageUrl } from "./editorExtensions";

describe("note Markdown persistence", () => {
  it("retains images, tables, task state, code, links and atomic references through editing and reload", () => {
    const markdown = '# 标题\n\n![视觉参考](mosael-asset:abc123)\n\n| 中文 | English |\n| --- | --- |\n| 内容 | value |\n\n- [x] 完成\n- [ ] Next\n\n```ts\nconst x = 1;\n```\n\n[网页](https://example.com) 和 [@参考](#/notes?note=abc&revision=3)\n';
    const editor = new Editor({ extensions: noteExtensions(), content: markdown, contentType: "markdown" });
    editor.commands.insertContentAt(editor.state.doc.content.size, {type: "paragraph", content:[{type:"text",text:"编辑后"}]});
    const saved = editor.getMarkdown();
    const reopened = new Editor({ extensions: noteExtensions(), content: saved, contentType:"markdown" });
    expect(reopened.getJSON()).toEqual(editor.getJSON());
    expect(saved).toContain('![视觉参考](mosael-asset:abc123)');
    expect(saved).toContain('- [x] 完成');
    expect(saved).toContain('[@参考](#/notes?note=abc&revision=3)');
    expect(reopened.view.dom.querySelectorAll('[data-note-reference]')).toHaveLength(1);
    expect(reopened.view.dom.querySelectorAll('table')).toHaveLength(1);
    expect(saved).not.toContain('token=');
    editor.destroy(); reopened.destroy();
  });
  it("keeps an ordinary link — NoteReference took over the link token and swallowed every non-note URL", () => {
    // 往返一致**不能**证明链接还在:第一次解析就被吃掉的话,存下来的和再读回来的都没有它,
    // 两边 JSON 照样相等。所以这里断言的是"链接确实在",而不是"前后一样"。
    const editor = new Editor({
      extensions: noteExtensions(),
      content: "看[这个页面](https://example.com/a?b=1)吧",
      contentType: "markdown",
    });
    const anchor = editor.view.dom.querySelector("a:not([data-note-reference])");
    expect(anchor?.getAttribute("href")).toBe("https://example.com/a?b=1");
    expect(anchor?.textContent).toBe("这个页面");
    // 链接文字也不能掉:曾经整段变成「看吧」,连字都没了。
    expect(editor.getText()).toBe("看这个页面吧");
    expect(editor.getMarkdown().trim()).toBe("看[这个页面](https://example.com/a?b=1)吧");
    editor.destroy();
  });

  it("still routes note deep links to the atomic reference node, not a plain link", () => {
    const editor = new Editor({
      extensions: noteExtensions(),
      content: "[@参考](#/notes?note=abc&revision=3)",
      contentType: "markdown",
    });
    expect(editor.view.dom.querySelectorAll("[data-note-reference]")).toHaveLength(1);
    expect(editor.getMarkdown().trim()).toBe("[@参考](#/notes?note=abc&revision=3)");
    editor.destroy();
  });

  it("does not render executable URLs or unsupported local paths as images", () => {
    expect(noteImageUrl('javascript:alert(1)')).toBe('');
    expect(noteImageUrl('file:///etc/passwd')).toBe('');
    expect(noteImageUrl('https://example.com/image.png')).toBe('https://example.com/image.png');
  });
});

it("keeps authenticated image URLs out of clipboard HTML", () => {
  const editor = new Editor({ extensions: noteExtensions(), content: '![image](mosael-asset:abc)', contentType: "markdown" });
  expect(editor.getHTML()).toContain('mosael-asset:abc');
  expect(editor.getHTML()).not.toContain('token=');
  editor.destroy();
});

it("preserves all six heading levels through Markdown and returns a heading to normal text", () => {
  const editor = new Editor({ extensions: noteExtensions(), content: "相机笔记 Camera notes", contentType: "markdown" });
  for (const level of [1, 2, 3, 4, 5, 6] as const) {
    editor.commands.setHeading({ level });
    const markdown = editor.getMarkdown();
    expect(markdown.trim()).toBe(`${"#".repeat(level)} 相机笔记 Camera notes`);
    const reopened = new Editor({ extensions: noteExtensions(), content: markdown, contentType: "markdown" });
    expect(reopened.getJSON()).toEqual(editor.getJSON());
    reopened.destroy();
  }
  editor.commands.setParagraph();
  expect(editor.getMarkdown().trim()).toBe("相机笔记 Camera notes");
  editor.destroy();
});
