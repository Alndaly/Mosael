import { describe, expect, it } from "vitest";

import {
  analyzeWorkflow,
  extractRefs,
  isNestedScopeConfig,
  outputType,
  typesCompatible,
  type AnalyzeContext,
  type RegistryLike,
} from "./analyze";
import type { WorkflowGraph } from "@/api/client";

const registry: RegistryLike = {
  get(type) {
    const table: Record<
      string,
      {
        config?: Record<string, { type?: string; required?: boolean; data_type?: string }>;
        output_types?: Record<string, string>;
      }
    > = {
      start: { config: { params: { type: "object" } } },
      llm: {
        config: {
          prompt: { type: "template", required: true },
          profile_id: { type: "string" },
        },
        output_types: { text: "text", json: "json" },
      },
      ai_generate: {
        config: { provider: { type: "string", required: true }, prompt: { type: "template", required: true } },
        output_types: { asset_id: "asset", generation_id: "text" },
      },
      // `data_type` 由后端按字段名推出来(见 domain/workflows.config_data_type),随节点声明
      // 一起发过来 —— 前端不再自己维护一张"哪个字段是素材"的表。
      transcribe_asset: { config: { asset_id: { type: "template", required: true, data_type: "asset" } } },
      template: { config: { template: { type: "template", required: true } } },
      subgraph: { config: { inputs: { type: "object" }, body: { type: "graph" }, output: { type: "template" } } },
    };
    return table[type];
  },
};

describe("outputType", () => {
  it("reads output types from the runtime registry instead of guessing from a node name", () => {
    const runtimeRegistry: RegistryLike = {
      get: () => ({ output_types: { artifact: "asset", count: "number" } }),
    };

    expect(outputType(runtimeRegistry, "plugin.example.runtime", "artifact")).toBe("asset");
    expect(outputType(runtimeRegistry, "plugin.example.runtime", "count")).toBe("number");
    expect(outputType(runtimeRegistry, "plugin.example.runtime", "undeclared")).toBe("any");
  });
});

const fullCtx: AnalyzeContext = {
  providerIds: new Set(["p1"]),
  providersLoaded: true,
  configuredGenProviders: new Set(["alibaba"]),
  genProvidersLoaded: true,
};

function graph(nodes: WorkflowGraph["nodes"], edges: WorkflowGraph["edges"] = []): WorkflowGraph {
  return { nodes, edges };
}

describe("extractRefs", () => {
  it("pulls source node ids out of a template", () => {
    expect(extractRefs("hi {{llm-1.text}} and {{start.q}}")).toEqual([
      { ref: "{{llm-1.text}}", sourceId: "llm-1" },
      { ref: "{{start.q}}", sourceId: "start" },
    ]);
  });
  it("ignores non-strings and plain text", () => {
    expect(extractRefs(42)).toEqual([]);
    expect(extractRefs("no vars here")).toEqual([]);
  });
  it("walks nested objects and arrays used by loop inputs and model parameters", () => {
    expect(
      extractRefs({ project_id: "{{project.project_id}}", nested: ["{{start.aspect_ratio}}", 30] }),
    ).toEqual([
      { ref: "{{project.project_id}}", sourceId: "project" },
      { ref: "{{start.aspect_ratio}}", sourceId: "start" },
    ]);
  });
});

describe("isNestedScopeConfig", () => {
  it("keeps parent validation out of loop and subgraph internal scopes", () => {
    expect(isNestedScopeConfig("loop_foreach", "body")).toBe(true);
    expect(isNestedScopeConfig("loop_foreach", "output")).toBe(true);
    expect(isNestedScopeConfig("subgraph", "body")).toBe(true);
    expect(isNestedScopeConfig("loop_foreach", "inputs")).toBe(false);
    expect(isNestedScopeConfig("llm", "body")).toBe(false);
  });
});

describe("typesCompatible", () => {
  it("any and text slots accept anything; concrete types must match", () => {
    expect(typesCompatible("text", "any")).toBe(true);
    expect(typesCompatible("asset", "any")).toBe(true);
    expect(typesCompatible("text", "text")).toBe(true);
    expect(typesCompatible("number", "text")).toBe(true); // text slot stringifies
    expect(typesCompatible("asset", "asset")).toBe(true);
    expect(typesCompatible("text", "asset")).toBe(false); // wiring text into an asset slot
    expect(typesCompatible("any", "asset")).toBe(true); // unknown source → don't alarm
  });
});

describe("analyzeWorkflow", () => {
  it("warns on a data edge whose output type mismatches a strong input slot", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "llm-1", type: "llm", config: { prompt: "hi", profile_id: "p1" } },
        { id: "tr", type: "transcribe_asset", config: { asset_id: "" } },
      ],
      [
        { id: "e1", source: "start", target: "llm-1" },
        // llm.text (text) → transcribe.asset_id (expects asset) → mismatch
        { id: "d1", source: "llm-1", target: "tr", kind: "data", source_output: "text", target_input: "asset_id" },
      ],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    const mismatch = a.byNode.get("tr")?.find((i) => i.code === "type-mismatch");
    expect(mismatch).toMatchObject({ severity: "warn", expected: "asset", actual: "text", configKey: "asset_id" });
    // 软提示不阻断运行。
    expect(a.runnable).toBe(true);
  });

  it("does not flag a subgraph node's output / inner refs as stale-var", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        {
          id: "sg",
          type: "subgraph",
          config: {
            inputs: { x: "{{start.q}}" },
            body: { nodes: [{ id: "t", type: "template", config: { template: "{{input.x}}" } }], edges: [] },
            output: "{{t.text}}", // 引用内部节点 t —— 不该被顶层判为失效
          },
        },
      ],
      [{ id: "e1", source: "start", target: "sg" }],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect((a.byNode.get("sg") ?? []).filter((i) => i.code === "stale-var")).toEqual([]);
  });

  it("does not warn when an asset output feeds an asset slot", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "gen", type: "ai_generate", config: { provider: "alibaba", prompt: "cat" } },
        { id: "tr", type: "transcribe_asset", config: { asset_id: "" } },
      ],
      [
        { id: "e1", source: "start", target: "gen" },
        { id: "d1", source: "gen", target: "tr", kind: "data", source_output: "asset_id", target_input: "asset_id" },
      ],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect(a.byNode.get("tr")?.some((i) => i.code === "type-mismatch")).toBeFalsy();
  });


  it("passes a fully-wired, configured graph", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: { params: { q: "" } } },
        { id: "llm-1", type: "llm", config: { prompt: "{{start.q}}", profile_id: "p1" } },
      ],
      [{ id: "e1", source: "start", target: "llm-1" }],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect(a.issues).toHaveLength(0);
    expect(a.runnable).toBe(true);
  });

  it("flags a missing required field as a blocking error", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "llm-1", type: "llm", config: { prompt: "", profile_id: "p1" } },
      ],
      [{ id: "e1", source: "start", target: "llm-1" }],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect(a.byNode.get("llm-1")?.[0]).toMatchObject({ code: "required-missing", configKey: "prompt", severity: "error" });
    expect(a.runnable).toBe(false);
  });

  it("flags a reference to a deleted node (stale-var)", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "tmpl", type: "template", config: { template: "{{ghost.text}}" } },
      ],
      [{ id: "e1", source: "start", target: "tmpl" }],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    const stale = a.byNode.get("tmpl")?.find((i) => i.code === "stale-var");
    expect(stale).toMatchObject({ ref: "{{ghost.text}}", configKey: "template", severity: "error" });
  });

  it("warns on a node unreachable from start", () => {
    const g = graph([
      { id: "start", type: "start", config: {} },
      { id: "tmpl", type: "template", config: { template: "x" } }, // no edge from start
    ]);
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect(a.byNode.get("tmpl")?.some((i) => i.code === "disconnected")).toBe(true);
    expect(a.severityByNode.get("tmpl")).toBe("warn");
  });

  it("blocks running when the workflow has no start node", () => {
    const a = analyzeWorkflow(graph([]), registry, fullCtx);
    expect(a.runnable).toBe(false);
    expect(a.issues[0]).toMatchObject({ code: "missing-start", severity: "error" });
  });

  it("errors when an LLM binds a provider profile that no longer exists", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "llm-1", type: "llm", config: { prompt: "hi", profile_id: "gone" } },
      ],
      [{ id: "e1", source: "start", target: "llm-1" }],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect(a.byNode.get("llm-1")?.some((i) => i.code === "provider-missing")).toBe(true);
    expect(a.runnable).toBe(false);
  });

  it("warns (not errors) when no providers exist at all", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "llm-1", type: "llm", config: { prompt: "hi" } },
      ],
      [{ id: "e1", source: "start", target: "llm-1" }],
    );
    const a = analyzeWorkflow(g, registry, {
      ...fullCtx,
      providerIds: new Set(),
    });
    expect(a.byNode.get("llm-1")?.some((i) => i.code === "no-providers" && i.severity === "warn")).toBe(true);
  });

  it("errors when an ai_generate provider has no configured key", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "gen", type: "ai_generate", config: { provider: "openai", prompt: "cat" } },
      ],
      [{ id: "e1", source: "start", target: "gen" }],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect(a.byNode.get("gen")?.some((i) => i.code === "gen-provider-unconfigured")).toBe(true);
  });

  it("holds binding checks until async data has loaded", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "llm-1", type: "llm", config: { prompt: "hi", profile_id: "p1" } },
      ],
      [{ id: "e1", source: "start", target: "llm-1" }],
    );
    const a = analyzeWorkflow(g, registry, {
      providerIds: new Set(),
      providersLoaded: false,
      configuredGenProviders: new Set(),
      genProvidersLoaded: false,
    });
    // profile_id is set but providers not loaded yet — don't false-alarm.
    expect(a.byNode.get("llm-1")?.some((i) => i.code === "provider-missing")).toBeFalsy();
  });
});
