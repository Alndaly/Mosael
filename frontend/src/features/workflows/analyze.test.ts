import { describe, expect, it } from "vitest";

import { analyzeWorkflow, extractRefs, type AnalyzeContext, type RegistryLike } from "./analyze";
import type { WorkflowGraph } from "@/api/client";

const registry: RegistryLike = {
  get(type) {
    const table: Record<string, { config?: Record<string, { type?: string; required?: boolean }> }> = {
      start: { config: { params: { type: "object" } } },
      llm: {
        config: {
          prompt: { type: "template", required: true },
          profile_id: { type: "string" },
        },
      },
      ai_generate: {
        config: { provider: { type: "string", required: true }, prompt: { type: "template", required: true } },
      },
      template: { config: { template: { type: "template", required: true } } },
    };
    return table[type];
  },
};

const fullCtx: AnalyzeContext = {
  providerIds: new Set(["p1"]),
  providersLoaded: true,
  configuredGenProviders: new Set(["alibaba"]),
  credentialsLoaded: true,
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
});

describe("analyzeWorkflow", () => {
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
      credentialsLoaded: false,
    });
    // profile_id is set but providers not loaded yet — don't false-alarm.
    expect(a.byNode.get("llm-1")?.some((i) => i.code === "provider-missing")).toBeFalsy();
  });
});
