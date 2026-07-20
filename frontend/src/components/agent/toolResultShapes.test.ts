/**
 * Unwrapping tool results, and deciding which of them can be shown as something better
 * than JSON.
 *
 * Both halves were silently broken: the runtimes hand the UI a JSON *string*, so the chat
 * rendered escaped JSON for every tool call and the asset-preview walker — which only
 * descends real objects — found nothing to preview.
 */
import { describe, expect, it } from "vitest";

import { detectShape, toolResultData } from "./toolResultShapes";

describe("toolResultData", () => {
  it("prefers the structured copy pi puts in details", () => {
    const rows = [{ id: "a", name: "clip", kind: "video" }];
    const result = { content: [{ type: "text", text: JSON.stringify(rows) }], details: { data: rows } };
    expect(toolResultData(result)).toEqual(rows);
  });

  it("parses the text content when there is no structured copy", () => {
    // Older sidecar builds, and any tool that has not been rebuilt yet.
    const rows = [{ id: "a", name: "clip", kind: "video" }];
    const result = { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }], details: {} };
    expect(toolResultData(result)).toEqual(rows);
  });

  it("unwraps the MCP {result: ...} envelope", () => {
    expect(toolResultData({ result: { ok: true } })).toEqual({ ok: true });
  });

  it("parses a bare JSON string", () => {
    expect(toolResultData('{"a":1}')).toEqual({ a: 1 });
  });

  it("leaves plain prose alone rather than mangling it", () => {
    expect(toolResultData("素材已更新")).toBe("素材已更新");
  });

  it("does not throw on malformed JSON", () => {
    expect(toolResultData("{not json")).toBe("{not json");
  });

  it("passes null through", () => {
    expect(toolResultData(null)).toBeNull();
  });
});

describe("detectShape", () => {
  it("recognises an asset list from either runtime", () => {
    // The MCP projection and the sidecar's full record differ in everything but these keys,
    // which is why dispatch is on shape rather than on the tool's name.
    const projection = [{ id: "a", name: "clip", kind: "video", duration_seconds: 12 }];
    const fullRecord = [
      { id: "a", name: "clip", kind: "video", workspace_id: "w", media_info: { duration: 12 } },
    ];
    expect(detectShape(projection)).toBe("assets");
    expect(detectShape(fullRecord)).toBe("assets");
  });

  it("does not mistake a KB search for an asset list", () => {
    // The failure this guards: a loose "array of objects" test rendered search results as a
    // broken asset list, which is worse than the JSON it replaced.
    const kb = [{ document_id: "d", title: "t", snippet: "s", score: 0.8 }];
    expect(detectShape(kb)).toBe("kb");
  });

  it("recognises web results", () => {
    expect(detectShape([{ title: "t", url: "https://x", snippet: "s" }])).toBe("search");
  });

  it("recognises a timeline", () => {
    expect(detectShape({ name: "seq", tracks: [{ name: "V1", clips: [] }] })).toBe("sequence");
  });

  it("recognises a confirmation handle", () => {
    expect(detectShape({ confirmation_id: "c", status: "pending", summary: "改时间线" })).toBe("confirmation");
  });

  it("treats one long body as prose", () => {
    expect(detectShape({ answer: "x".repeat(200), provider: "p" })).toBe("text");
  });

  it("leaves a short body alone — a two-word answer is not a document", () => {
    expect(detectShape({ answer: "好的" })).toBeNull();
  });

  it("falls back to null for anything unrecognised", () => {
    expect(detectShape({ applied_operations: 3, sequence_revision: 12 })).toBeNull();
    expect(detectShape([])).toBeNull();
    expect(detectShape("plain text")).toBeNull();
    expect(detectShape(null)).toBeNull();
  });

  it("does not match a partial list where only some rows have the keys", () => {
    // Half-rendering a list is worse than not rendering it.
    expect(detectShape([{ id: "a", name: "n", kind: "video" }, { id: "b" }])).toBeNull();
  });
});
