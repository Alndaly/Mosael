import type { BoardItem } from "@/api/domains/boards";
import type { NoteReference } from "@/api/domains/notes";
export type BoardDocumentState = {
  reference?: NoteReference;
  pending: boolean;
  error?: string;
};

/** Preview may be shortened; generation always receives the complete pinned source. */
export function boardSourceText(
  item: BoardItem,
  document?: BoardDocumentState,
): string {
  if (item.kind === "note") return (item.text ?? "").trim();
  if (
    item.kind !== "document" ||
    !document?.reference ||
    document.error ||
    document.pending
  )
    return "";
  return document.reference.markdown.trim();
}
export function boardDocumentBlocked(
  item: BoardItem,
  document?: BoardDocumentState,
): boolean {
  return (
    item.kind === "document" &&
    ((!item.note_id && !item.asset_id) ||
      !document?.reference ||
      !!document.error ||
      document.pending)
  );
}

export function documentPrompt(
  prompt: string,
  references: NoteReference[],
): string {
  if (!references.length) return prompt;
  return [
    prompt,
    "Reference documents (source material):",
    //: 文档素材(ADR 0031)没有笔记那种引用地址,只写标题。
    ...references.map(
      (ref) => `${ref.citation_url ? `[${ref.title}](${ref.citation_url})` : ref.title}\n${ref.markdown}`,
    ),
  ].join("\n\n");
}
