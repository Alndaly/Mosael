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
    (!item.note_id ||
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
    ...references.map(
      (ref) => `[${ref.title}](${ref.citation_url})\n${ref.markdown}`,
    ),
  ].join("\n\n");
}
