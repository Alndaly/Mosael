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

it("接管了 link token 就得连标题一起还回去", () => {
  // NoteReference 用 markdownTokenName:"link" 接管了**所有**链接,所以它继承了上游 Link 的义务。
  // 第一版只还了 href —— `[文字](地址 "悬浮提示")` 的标题被吞掉,形状和当初吞掉整条链接一样:
  // 接管了别人的 token,只还回自己看得懂的那部分。
  const source = '读一读[这篇](https://example.com/a "悬浮提示")再说。';
  const editor = new Editor({ extensions: noteExtensions(), content: source, contentType: "markdown" });
  expect(editor.getMarkdown().trim()).toBe(source);
  // 笔记深链仍然走原子引用节点,不受影响。
  const reference = new Editor({
    extensions: noteExtensions(),
    content: "见 [@某笔记](#/notes?note=abc-123)",
    contentType: "markdown",
  });
  expect(reference.getJSON().content?.[0]?.content?.[1]?.type).toBe("noteReference");
  editor.destroy();
  reference.destroy();
});

describe("表格单元格里的竖线", () => {
  const roundTrip = (markdown: string) => {
    const editor = new Editor({ extensions: noteExtensions(), content: markdown, contentType: "markdown" });
    const out = editor.getMarkdown();
    editor.destroy();
    return out;
  };

  it("竖线要转义,否则那一格被读成两格", () => {
    // 上游的序列化器把 `|` 当成永远的列分隔符,正文里出现它就当场把单元格切开。
    const once = roundTrip("| a | b |\n| --- | --- |\n| x \\| y | 2 |");
    expect(once).toContain("x \\| y");

    const editor = new Editor({ extensions: noteExtensions(), content: once, contentType: "markdown" });
    const cells = Array.from(editor.view.dom.querySelectorAll("tbody td"), (td) => td.textContent);
    editor.destroy();
    // 两列,不是三列:那一格仍然是完整的一格。
    expect(cells).toEqual(["x | y", "2"]);
  });

  it("再存一次形状不再继续变", () => {
    // 这才是这条最要命的地方:此前一遍丢转义、两遍真的裂成两列,反复保存会一路劣化。
    const once = roundTrip("| a | b |\n| --- | --- |\n| x \\| y | 2 |");
    expect(roundTrip(once).trim()).toBe(once.trim());
  });
});
