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
