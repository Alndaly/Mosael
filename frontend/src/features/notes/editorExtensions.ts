import { Node } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { createNoteImage } from "./NoteImage";
import { createNoteCodeBlock } from "./NoteCodeBlock";
export { noteImageUrl } from "./NoteImage";
import { TableKit } from "@tiptap/extension-table";
import { NoteTable } from "./NoteTable";
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
   *
   * **还回去就要还完整。** 第一版只还了 href，`[文字](地址 "悬浮提示")` 的标题被吞掉了 ——
   * 上游 Link 自己的 parseMarkdown 是带 title 的，而我们把它整个接管了，就继承了它的义务。
   * 丢的东西比丢链接小，但形状一模一样：接管了别人的 token，却只还回自己看得懂的那部分。
   */
  parseMarkdown: (token, h) => /^#\/notes\?note=[\w-]+(?:&revision=\d+)?$/.test(String(token.href))
    ? h.createNode("noteReference", { href: token.href, label: String(token.text || "").replace(/^@/, "") })
    : h.applyMark("link", h.parseInline(token.tokens ?? []), {
        href: String(token.href ?? ""),
        title: token.title || null,
      }),
  renderMarkdown: node => `[@${String(node.attrs?.label || "").replace(/[\\[\]]/g, "\\$&")}](${node.attrs?.href})`,
});

/**
 * 占位符只属于**空段落**。
 *
 * `editor.isEmpty` 把「文档里只有一个空代码块」也算作空文档,于是占位符被挂到代码块上,
 * 它的 `::before` 浮在代码块头部那一行 —— 正好压住语言选择器,两段文字叠在一起。
 */
export const notePlaceholder =
  (text: string) =>
  ({ node }: { node: { type: { name: string } } }) =>
    node.type.name === "paragraph" ? text : "";

export function noteExtensions(readonly = false, locale = "zh-CN") {
  return [StarterKit.configure({ codeBlock: false, link: { openOnClick: readonly } }), NoteReference, createNoteImage(locale), createNoteCodeBlock(locale),
    TableKit.configure({ table: false }), NoteTable, TaskList, TaskItem.configure({ nested: true }), Markdown];
}
