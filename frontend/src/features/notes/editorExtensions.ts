import { Node, mergeAttributes } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Image from "@tiptap/extension-image";
import { TableKit } from "@tiptap/extension-table";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import { Markdown } from "@tiptap/markdown";
import { assetPreviewUrl } from "@/api/domains/assets";

// Store stable references in Markdown, never session tokens or server addresses.
export function noteImageUrl(src: string): string {
  const asset = /^mosael-asset:([a-zA-Z0-9-]+)$/.exec(src);
  if (asset) return assetPreviewUrl(asset[1]);
  return /^(https?:\/\/|data:image\/(?:png|jpeg|webp|gif);base64,)/i.test(src) ? src : "";
}
const NoteImage = Image.extend({
  renderHTML({ HTMLAttributes }) {
    const src = String(HTMLAttributes.src || "");
    return ["img", mergeAttributes(HTMLAttributes, { src: src.startsWith("mosael-asset:") ? src : noteImageUrl(src) })];
  },
  // Node views render authenticated media; HTML/Markdown serialization stays credential-free.
  addNodeView() {
    return ({ node }) => {
      const img = document.createElement("img");
      img.src = noteImageUrl(String(node.attrs.src || ""));
      img.alt = String(node.attrs.alt || "");
      if (node.attrs.title) img.title = String(node.attrs.title);
      img.loading = "lazy";
      return { dom: img };
    };
  },
}).configure({ allowBase64: true });

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

export function noteExtensions(readonly = false) {
  return [StarterKit.configure({ link: { openOnClick: readonly } }), NoteReference, NoteImage,
    TableKit, TaskList, TaskItem.configure({ nested: true }), Markdown];
}
