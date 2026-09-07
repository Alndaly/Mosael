import { describe, expect, it } from "vitest";
import {
  boardSourceText,
  boardDocumentBlocked,
  documentPrompt,
} from "./boardDocumentSources";
import type { BoardItem } from "@/api/domains/boards";
const item: BoardItem = {
  id: "doc",
  kind: "document",
  x: 0,
  y: 0,
  note_id: "n",
  note_revision: 2,
  text: "Title only",
};
const reference = {
  note_id: "n",
  revision: 2,
  title: "Title",
  markdown: "# Source\n\n" + "完整正文".repeat(6000),
  tags: [],
  citation_url: "#/notes?note=n&revision=2",
};
describe("document generation sources", () => {
  it("feeds the complete pinned body rather than the card title or shortened preview", () => {
    expect(boardSourceText(item, { reference, pending: false })).toBe(
      reference.markdown,
    );
    expect(boardDocumentBlocked(item, { reference, pending: false })).toBe(
      false,
    );
  });
  it("blocks missing, loading and deleted sources, including stale cached content", () => {
    for (const state of [
      undefined,
      { pending: true },
      { pending: false, error: "deleted", reference },
    ]) {
      expect(boardDocumentBlocked(item, state)).toBe(true);
      expect(boardSourceText(item, state)).toBe("");
    }
  });
  it("keeps the instruction and complete reference together in generation input", () => {
    expect(documentPrompt("Write a launch video", [reference])).toContain(
      reference.markdown,
    );
    expect(documentPrompt("Write a launch video", [reference])).toMatch(
      /^Write a launch video/,
    );
    expect(documentPrompt("plain", [])).toBe("plain");
  });
  it("preserves sticky notes as independent editable text", () => {
    const note: BoardItem = { ...item, kind: "note", text: "  Script  " };
    expect(boardSourceText(note)).toBe("Script");
    expect(boardDocumentBlocked(note)).toBe(false);
  });
});
