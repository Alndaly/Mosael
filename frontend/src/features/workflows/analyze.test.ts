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
        required_one_of?: string[][];
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
      // 二选一:克隆音色或引擎音色。两边都不是 required(标了就是撒谎),靠 required_one_of。
      synthesize_speech: {
        config: {
          text: { type: "template", required: true },
          voice_id: { type: "string" },
          engine_voice: { type: "string" },
        },
        required_one_of: [["voice_id", "engine_voice"]],
      },
      subgraph: { config: { inputs: { type: "object" }, body: { type: "graph" }, output: { type: "template" } } },
      loop_foreach: {
        config: { items: { type: "template", required: true }, body: { type: "graph" }, output: { type: "template" } },
      },
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


describe("二选一的必填", () => {
  /**
   * per-field 的 `required` 表达不了「这几个里至少要有一个」。语音合成要么克隆音色、
   * 要么引擎音色:两边都标必填是撒谎(填了一边照样被红星拦),两边都不标则**一个都没选**
   * 这件事在画布上看不出来 —— 节点是绿的,跑到那一步才失败,而那时前面几步已经花过时间和钱。
   */
  const node = (config: Record<string, unknown>) =>
    graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "sp", type: "synthesize_speech", config },
      ],
      [{ id: "e1", source: "start", target: "sp" }],
    );

  it("一个都没填就报错，并指向组里第一个字段", () => {
    const a = analyzeWorkflow(node({ text: "念一句" }), registry, fullCtx);
    expect(a.byNode.get("sp")).toContainEqual(
      expect.objectContaining({ code: "required-missing", configKey: "voice_id", severity: "error" }),
    );
    expect(a.runnable).toBe(false);
  });

  it("填了任意一个就不报", () => {
    for (const filled of [{ voice_id: "v1" }, { engine_voice: "zh_female_x" }]) {
      const a = analyzeWorkflow(node({ text: "念一句", ...filled }), registry, fullCtx);
      const missing = (a.byNode.get("sp") ?? []).filter((i) => i.code === "required-missing");
      expect(missing, JSON.stringify(filled)).toEqual([]);
    }
  });

  it("由数据边接上的也算填了", () => {
    // 上游算出一个音色 id 接过来 —— 那和手填是同一件事,不该报"没填"。
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "sp", type: "synthesize_speech", config: { text: "念一句", voice_id: "" } },
      ],
      [
        { id: "e1", source: "start", target: "sp" },
        { id: "d1", source: "start", target: "sp", kind: "data", source_output: "params", target_input: "voice_id" },
      ],
    );
    const missing = (analyzeWorkflow(g, registry, fullCtx).byNode.get("sp") ?? []).filter(
      (i) => i.code === "required-missing",
    );
    expect(missing).toEqual([]);
  });
});


describe("循环体和子图里的节点", () => {
  /**
   * 此前只走顶层,于是体里的节点从没被检查过 —— 而最贵的那几步恰恰住在里面(示范模板的
   * 整个"逐镜生成"都在循环体里)。表现是画布全绿、点了运行、前面几步跑完花了钱,才在
   * 循环里第一镜上失败。
   */
  const withBody = (inner: Record<string, unknown>[]) =>
    graph(
      [
        { id: "start", type: "start", config: {} },
        {
          id: "loop",
          type: "loop_foreach",
          name: "逐镜生成",
          config: { items: "{{start.params}}", body: { nodes: inner, edges: [] } },
        },
      ],
      [{ id: "e1", source: "start", target: "loop" }],
    );

  it("体里缺必填也要拦住运行", () => {
    const a = analyzeWorkflow(withBody([{ id: "inner", type: "template", name: "拼一句", config: { template: "" } }]), registry, fullCtx);
    expect(a.runnable).toBe(false);
    expect(a.errorCount).toBe(1);
  });

  it("问题记在外层那个节点头上，名字带路径", () => {
    // 画布上只画得出顶层节点 —— 给一个画不出来的 id 挂角标,等于这条问题没人看得见。
    const a = analyzeWorkflow(withBody([{ id: "inner", type: "template", name: "拼一句", config: { template: "" } }]), registry, fullCtx);
    expect(a.byNode.get("inner")).toBeUndefined();
    expect(a.byNode.get("loop")).toEqual([
      expect.objectContaining({ nodeId: "loop", nodeName: "逐镜生成 › 拼一句", code: "required-missing" }),
    ]);
    expect(a.severityByNode.get("loop")).toBe("error");
  });

  it("体里的 {{loop.*}} / {{input.*}} 不算失效引用", () => {
    // 它们引用的不是节点,是这一层注入的变量。不认的话,递归下去会把每一条正常引用都报成失效
    // —— 那比不检查更糟:满屏红点,而真正的问题淹在里面。
    const a = analyzeWorkflow(
      withBody([
        { id: "inner", type: "template", config: { template: "{{loop.item.narration}} / {{input.voice_id}}" } },
      ]),
      registry,
      fullCtx,
    );
    expect(a.issues.filter((i) => i.code === "stale-var")).toEqual([]);
    expect(a.runnable).toBe(true);
  });

  it("体里引用一个不存在的兄弟节点仍然要报", () => {
    const a = analyzeWorkflow(
      withBody([{ id: "inner", type: "template", config: { template: "{{nobody.text}}" } }]),
      registry,
      fullCtx,
    );
    expect(a.issues).toContainEqual(expect.objectContaining({ code: "stale-var", ref: "{{nobody.text}}" }));
  });

  it("体里没有 start 不算缺开始节点", () => {
    // 循环体由外层驱动,它本来就没有 start。
    const a = analyzeWorkflow(withBody([{ id: "inner", type: "template", config: { template: "ok" } }]), registry, fullCtx);
    expect(a.issues.filter((i) => i.code === "missing-start")).toEqual([]);
  });
});
