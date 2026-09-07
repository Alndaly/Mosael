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
  parseMarkdown: (token, h) => /^#\/notes\?note=[\w-]+(?:&revision=\d+)?$/.test(String(token.href))
    ? h.createNode("noteReference", { href: token.href, label: String(token.text || "").replace(/^@/, "") }) : [],
  renderMarkdown: node => `[@${String(node.attrs?.label || "").replace(/[\\[\]]/g, "\\$&")}](${node.attrs?.href})`,
});

export function noteExtensions(readonly = false, locale = "zh-CN") {
  return [StarterKit.configure({ codeBlock: false, link: { openOnClick: readonly } }), NoteReference, createNoteImage(locale), createNoteCodeBlock(locale),
    TableKit, TaskList, TaskItem.configure({ nested: true }), Markdown];
}
