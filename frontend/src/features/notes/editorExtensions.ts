import { Node } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { createNoteImage } from "./NoteImage";
import { createNoteCodeBlock } from "./NoteCodeBlock";
export { noteImageUrl } from "./NoteImage";
import { TableKit } from "@tiptap/extension-table";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import { Markdown } from "@tiptap/markdown";
export const NoteReference = Node.create({
  name: "noteReference", priority: 1100, inline: true, group: "inline", atom: true,
  addAttributes: () => ({ href: { default: "" }, label: { default: "" } }),
  parseHTML: () => [{ tag: "a[data-note-reference]", getAttrs: el => ({ href: el.getAttribute("href"), label: el.textContent }) }],
  renderHTML: ({ node }) => ["a", { href: node.attrs.href, "data-note-reference": "", class: "note-reference", title: node.attrs.label }, `@${node.attrs.label}`],
  renderText: ({ node }) => `@${node.attrs.label}`,
  markdownTokenName: "link",
  /**
   * 这个节点**接管了 Markdown 里所有的 link token**（`markdownTokenName: "link"` + 高 priority），
   * 所以它有义务把不属于自己的那些**还回去**。
   *
   * 此前不匹配时返回 `[]` —— 而空数组的意思是「这个 token 不产生任何内容」，于是**每一个普通
   * 链接都被吃掉**：`和[链接](https://example.com)。` 在富文本里变成 `和。`，连字都没了。
   * 更糟的是它不只是显示问题：Markdown 视图仍是原文，但只要在富文本里动一下（敲一个字符就够），
   * 丢了链接的文档就被写回去，链接从此真的没了，且没有任何提示。
   *
   * 所以非笔记链接要交还成一个正常的 link mark，而不是丢掉。
   */
  parseMarkdown: (token, h) => /^#\/notes\?note=[\w-]+(?:&revision=\d+)?$/.test(String(token.href))
    ? h.createNode("noteReference", { href: token.href, label: String(token.text || "").replace(/^@/, "") })
    : h.applyMark("link", h.parseInline(token.tokens ?? []), { href: String(token.href ?? "") }),
  renderMarkdown: node => `[@${String(node.attrs?.label || "").replace(/[\\[\]]/g, "\\$&")}](${node.attrs?.href})`,
});

export function noteExtensions(readonly = false, locale = "zh-CN") {
  return [StarterKit.configure({ codeBlock: false, link: { openOnClick: readonly } }), NoteReference, createNoteImage(locale), createNoteCodeBlock(locale),
    TableKit, TaskList, TaskItem.configure({ nested: true }), Markdown];
}
