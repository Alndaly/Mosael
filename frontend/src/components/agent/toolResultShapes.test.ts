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
    expect(detectShape({ answer: "好的" })).toBe("text");
  });

  it("falls back to null for anything unrecognised", () => {
    expect(detectShape({ applied_operations: 3, sequence_revision: 12 })).toBe("summary");
    expect(detectShape([])).toBe("empty");
    expect(detectShape("plain text")).toBe("text");
    expect(detectShape(null)).toBeNull();
  });

  it("does not match a partial list where only some rows have the keys", () => {
    // It should not half-render as an asset list; the generic row card is the safe fallback.
    expect(detectShape([{ id: "a", name: "n", kind: "video" }, { id: "b" }])).toBe("records");
  });
});

describe("asset rows", () => {
  it("keeps a duration off images", () => {
    // "image · 0:00" reads as a broken value, not as "images have no length".
    const rows = [{ id: "a", name: "photo.jpg", kind: "image", duration_seconds: 0 }];
    expect(detectShape(rows)).toBe("assets");
  });
});

describe("single-object shapes (get_workflow / update_asset_tags)", () => {
  it("recognises a workflow by its graph, not its tool name", () => {
    expect(
      detectShape({ id: "w1", name: "发布流", graph: { nodes: [{ id: "start", type: "start" }], edges: [] } }),
    ).toBe("workflow");
  });

  it("does not mistake an object with a non-graph `graph` key", () => {
    expect(detectShape({ graph: "not-a-graph" })).toBe("summary");
  });

  it("recognises a tagging result: asset + new tag set", () => {
    expect(detectShape({ asset_id: "a1", name: "素材.mp4", tags: ["旅行", "vlog"] })).toBe("tagged");
  });

});

describe("common tool and workflow result cards", () => {
  it("recognises workflow asset-query bundles", () => {
    expect(
      detectShape({
        assets: [{ id: "a1", name: "素材.mp4", kind: "video", duration: 12 }],
        ids: ["a1"],
        count: 1,
      }),
    ).toBe("assetBundle");
  });

  it("recognises generated/exported asset references", () => {
    expect(detectShape({ asset_id: "a1", generation_id: "g1" })).toBe("assetRef");
  });

  it("recognises workflow batch update results", () => {
    expect(detectShape({ updated: [{ id: "a1", name: "素材.mp4", tags: ["悬疑"] }], count: 1 })).toBe("updated");
  });

  it("recognises id-only creation/job results", () => {
    expect(detectShape({ workflow_id: "w1", nodes: 6 })).toBe("refs");
    expect(detectShape({ project_id: "p1", name: "新项目" })).toBe("refs");
    expect(detectShape({ job_id: "j1" })).toBe("refs");
  });

  it("recognises plugin output envelopes", () => {
    expect(detectShape({ status: "succeeded", output: { ok: true }, error: null })).toBe("pluginOutput");
  });

  it("recognises nested result lists from workflow nodes", () => {
    expect(detectShape({ text: "匹配 1 条", results: [{ id: "r1", score: 0.9 }] })).toBe("nestedResults");
  });

  it("uses generic rows for otherwise valid object lists", () => {
    expect(detectShape([{ plugin_id: "p1", tool_name: "t", description: "desc" }])).toBe("records");
  });
});
