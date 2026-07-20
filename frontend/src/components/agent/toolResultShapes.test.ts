/**
 * Unwrapping tool results, and deciding which of them can be shown as something better
 * than JSON.
 *
 * Both halves were silently broken: the runtimes hand the UI a JSON *string*, so the chat
 * rendered escaped JSON for every tool call and the asset-preview walker — which only
 * descends real objects — found nothing to preview.
 */
import { describe, expect, it } from "vitest";

import { toolResultData } from "./toolResultShapes";

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
