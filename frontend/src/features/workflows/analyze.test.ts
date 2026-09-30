import { describe, expect, it } from "vitest";

import {
  analyzeWorkflow,
  extractRefs,
  isNestedScopeConfig,
  issuesAtLayer,
  outputType,
  worstSeverity,
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
        config?: Record<string, { type?: string; required?: boolean; data_type?: string; default?: string; depends_on?: string; active_when?: Record<string, unknown>; one_of?: string }>;
        output_types?: Record<string, string>;
        body_scope?: Record<string, string[]>;
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
      // 提示词不在声明里标必填:要不要写由选中的模型说(见 AnalyzeContext.generationPromptMode)。
      ai_generate: {
        config: { provider: { type: "string", required: true }, prompt: { type: "template" } },
        output_types: { asset_id: "asset", generation_id: "text" },
      },
      // `data_type` 由后端按字段名推出来(见 domain/workflows.config_data_type),随节点声明
      // 一起发过来 —— 前端不再自己维护一张"哪个字段是素材"的表。
      transcribe_asset: { config: { asset_id: { type: "template", required: true, data_type: "asset" } } },
      template: { config: { template: { type: "template", required: true } } },
      // 音色是一格(引擎决定它指什么),普通的必填就表达得了。
      synthesize_speech: {
        config: {
          text: { type: "template", required: true },
          engine: { type: "string", default: "clone" },
          voice: { type: "string", required: true, depends_on: "engine" },
        },
      },
      conditional: {
        config: {
          engine: { type: "string", required: true, default: "google" },
          profile_id: { type: "string", required: true, active_when: { engine: "ai" } },
        },
      },
      // 素材和本机路径恰好填一个(NODE_TYPES 的 one_of)。
      browser_upload: {
        config: {
          asset_id: { type: "template", one_of: "source" },
          file_path: { type: "template", one_of: "source" },
        },
      },
      // 体内看得见哪些作用域名,由后端随节点声明发下来(NODE_TYPES 的 body_scope)。
      subgraph: {
        config: { inputs: { type: "object" }, body: { type: "graph" }, output: { type: "template" } },
        body_scope: { input: ["*inputs"] },
      },
      loop_foreach: {
        config: { items: { type: "template", required: true }, body: { type: "graph" }, output: { type: "template" } },
        body_scope: { loop: ["item", "index"], input: ["*inputs"] },
      },
      loop_while: {
        config: { body: { type: "graph" }, condition: { type: "template" }, output: { type: "template" } },
        body_scope: { loop: ["index"] },
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
  chatProfileIds: new Set(["p1"]),
  chatProfilesLoaded: true,
  generationVendors: new Set(["alibaba"]),
  generationModelsLoaded: true,
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
    expect(isNestedScopeConfig(registry, "loop_foreach", "body")).toBe(true);
    expect(isNestedScopeConfig(registry, "loop_foreach", "output")).toBe(true);
    expect(isNestedScopeConfig(registry, "loop_while", "condition")).toBe(true);
    expect(isNestedScopeConfig(registry, "subgraph", "body")).toBe(true);
    expect(isNestedScopeConfig(registry, "loop_foreach", "inputs")).toBe(false);
    expect(isNestedScopeConfig(registry, "llm", "body")).toBe(false);
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
    const mismatch = issuesAtLayer(a.issues, []).get("tr")?.find((i) => i.code === "type-mismatch");
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
    expect((issuesAtLayer(a.issues, []).get("sg") ?? []).filter((i) => i.code === "stale-var")).toEqual([]);
  });

  it("flags a loop output / loop_while condition that references nothing inside the body", () => {
    // 这两格在体内作用域里解析 —— 此前直接跳过,写错一个节点名运行时就是空串、条件循环只跑一轮。
    const body = { nodes: [{ id: "t", type: "template", config: { template: "{{loop.index}}" } }], edges: [] };
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        // 引用外层的 start、或体里没有的节点:都解析不了。
        { id: "each", type: "loop_foreach", config: { items: "a", body, output: "{{start.q}}" } },
        { id: "again", type: "loop_while", config: { body, condition: "{{ghost.text}}", output: "{{t.text}}" } },
      ],
      [
        { id: "e1", source: "start", target: "each" },
        { id: "e2", source: "start", target: "again" },
      ],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    const stale = (id: string) =>
      (issuesAtLayer(a.issues, []).get(id) ?? []).filter((i) => i.code === "stale-var").map((i) => [i.configKey, i.ref]);
    expect(stale("each")).toEqual([["output", "{{start.q}}"]]);
    // output 引用体里的 t、作用域名 loop 都合法;只有条件里的 ghost 不在。
    expect(stale("again")).toEqual([["condition", "{{ghost.text}}"]]);
    expect(a.runnable).toBe(false);
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
    expect(issuesAtLayer(a.issues, []).get("tr")?.some((i) => i.code === "type-mismatch")).toBeFalsy();
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
    expect(issuesAtLayer(a.issues, []).get("llm-1")?.[0]).toMatchObject({ code: "required-missing", configKey: "prompt", severity: "error" });
    expect(a.runnable).toBe(false);
  });

  it("only requires fields active for the current configuration", () => {
    const make = (engine: string) => graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "c", type: "conditional", config: { engine } },
      ],
      [{ id: "e", source: "start", target: "c" }],
    );
    expect(analyzeWorkflow(make("google"), registry, fullCtx).runnable).toBe(true);
    expect(issuesAtLayer(analyzeWorkflow(make("ai"), registry, fullCtx).issues, []).get("c")).toEqual([
      expect.objectContaining({ code: "required-missing", configKey: "profile_id" }),
    ]);
  });

  it("开始节点点名为必填的参数空着是阻塞错误,说清是哪一个;数字 0 不算空", () => {
    const make = (params: Record<string, unknown>) =>
      graph(
        [
          { id: "start", type: "start", config: { params, required_params: "product_name， selling_points, count" } },
          { id: "llm-1", type: "llm", config: { prompt: "{{start.product_name}}", profile_id: "p1" } },
        ],
        [{ id: "e1", source: "start", target: "llm-1" }],
      );
    const filled = analyzeWorkflow(make({ product_name: "开衫", selling_points: "不起球", count: 0 }), registry, fullCtx);
    expect(filled.runnable).toBe(true);
    const blank = analyzeWorkflow(make({ product_name: "开衫", selling_points: "  ", count: 0 }), registry, fullCtx);
    expect(blank.runnable).toBe(false);
    expect(issuesAtLayer(blank.issues, []).get("start")).toEqual([
      expect.objectContaining({ code: "required-missing", configKey: "selling_points", severity: "error" }),
    ]);
  });

  it("同组(one_of)恰好填一个:都填了、都没填都是阻塞错误,接了上游也算填了", () => {
    const make = (config: Record<string, unknown>, bound?: string) =>
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "up", type: "browser_upload", config },
        ],
        [
          { id: "e", source: "start", target: "up" },
          ...(bound ? [{ id: "d", source: "start", target: "up", kind: "data", target_input: bound }] : []),
        ] as WorkflowGraph["edges"],
      );
    const issuesOf = (g: WorkflowGraph) => issuesAtLayer(analyzeWorkflow(g, registry, fullCtx).issues, []).get("up") ?? [];

    expect(issuesOf(make({ asset_id: "a1" }))).toEqual([]);
    expect(issuesOf(make({ file_path: "/tmp/x.mp4" }))).toEqual([]);
    expect(issuesOf(make({}, "asset_id"))).toEqual([]);
    expect(issuesOf(make({ asset_id: "a1", file_path: "/tmp/x.mp4" }))).toEqual([
      expect.objectContaining({ code: "one-of-both", severity: "error", group: ["asset_id", "file_path"] }),
    ]);
    expect(issuesOf(make({ file_path: "/tmp/x.mp4" }, "asset_id"))).toEqual([
      expect.objectContaining({ code: "one-of-both" }),
    ]);
    expect(issuesOf(make({}))).toEqual([
      expect.objectContaining({ code: "one-of-missing", severity: "error", group: ["asset_id", "file_path"] }),
    ]);
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
    const stale = issuesAtLayer(a.issues, []).get("tmpl")?.find((i) => i.code === "stale-var");
    expect(stale).toMatchObject({ ref: "{{ghost.text}}", configKey: "template", severity: "error" });
  });

  it("warns on a node unreachable from start", () => {
    const g = graph([
      { id: "start", type: "start", config: {} },
      { id: "tmpl", type: "template", config: { template: "x" } }, // no edge from start
    ]);
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect(issuesAtLayer(a.issues, []).get("tmpl")?.some((i) => i.code === "disconnected")).toBe(true);
    expect(worstSeverity(issuesAtLayer(a.issues, []).get("tmpl") ?? [])).toBe("warn");
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
    expect(issuesAtLayer(a.issues, []).get("llm-1")?.some((i) => i.code === "provider-missing")).toBe(true);
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
      chatProfileIds: new Set(),
    });
    expect(issuesAtLayer(a.issues, []).get("llm-1")?.some((i) => i.code === "no-providers" && i.severity === "warn")).toBe(true);
  });

  it("errors when an ai_generate provider has no usable generation model", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "gen", type: "ai_generate", config: { provider: "openai", prompt: "cat" } },
      ],
      [{ id: "e1", source: "start", target: "gen" }],
    );
    const a = analyzeWorkflow(g, registry, fullCtx);
    expect(issuesAtLayer(a.issues, []).get("gen")?.some((i) => i.code === "gen-provider-unconfigured")).toBe(true);
  });

  it("ai_generate 的提示词要不要写由选中的模型说:不收的、可以不写的空着不报,要写的空着报", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "gen", type: "ai_generate", config: { provider: "alibaba", model: "upscale", prompt: "" } },
      ],
      [{ id: "e1", source: "start", target: "gen" }],
    );
    const missingPrompt = (ctx: AnalyzeContext) =>
      issuesAtLayer(analyzeWorkflow(g, registry, ctx).issues, []).get("gen")?.some(
        (i) => i.code === "required-missing" && i.configKey === "prompt",
      ) ?? false;
    // 模型清单还没到(没给判据):和以前一样按要写拦。
    expect(missingPrompt(fullCtx)).toBe(true);
    expect(missingPrompt({ ...fullCtx, generationPromptMode: () => "required" })).toBe(true);
    expect(missingPrompt({ ...fullCtx, generationPromptMode: () => "optional" })).toBe(false);
    expect(missingPrompt({ ...fullCtx, generationPromptMode: () => "none" })).toBe(false);
    // 判据拿到的是这个节点自己的配置
    const seen: Array<Record<string, unknown>> = [];
    analyzeWorkflow(g, registry, { ...fullCtx, generationPromptMode: (config) => (seen.push(config), "none") });
    expect(seen[0]).toMatchObject({ model: "upscale" });
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
      chatProfileIds: new Set(),
      chatProfilesLoaded: false,
      generationVendors: new Set(),
      generationModelsLoaded: false,
    });
    // profile_id is set but providers not loaded yet — don't false-alarm.
    expect(issuesAtLayer(a.issues, []).get("llm-1")?.some((i) => i.code === "provider-missing")).toBeFalsy();
  });

  it("生成模型清单没到之前,不报生成服务商没配", () => {
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "gen", type: "ai_generate", config: { provider: "openai", prompt: "cat" } },
      ],
      [{ id: "e1", source: "start", target: "gen" }],
    );
    const codes = (ctx: AnalyzeContext) => (issuesAtLayer(analyzeWorkflow(g, registry, ctx).issues, []).get("gen") ?? []).map((i) => i.code);
    expect(codes({ ...fullCtx, generationVendors: new Set(), generationModelsLoaded: false })).not.toContain(
      "gen-provider-unconfigured",
    );
    expect(codes({ ...fullCtx, generationVendors: new Set(), generationModelsLoaded: true })).toContain(
      "gen-provider-unconfigured",
    );
  });
});


describe("语音节点的音色", () => {
  /**
   * 音色只有一格:引擎决定它指配音库里的哪把,还是某个引擎的哪个。此前存成两个键、靠
   * 「二选一」规则判必填 —— 现在一格必填就够了,不需要额外的规则。
   */
  const node = (config: Record<string, unknown>) =>
    graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "sp", type: "synthesize_speech", config },
      ],
      [{ id: "e1", source: "start", target: "sp" }],
    );

  it("没选音色就报错", () => {
    const a = analyzeWorkflow(node({ text: "念一句", engine: "edge" }), registry, fullCtx);
    expect(issuesAtLayer(a.issues, []).get("sp")).toContainEqual(
      expect.objectContaining({ code: "required-missing", configKey: "voice", severity: "error" }),
    );
    expect(a.runnable).toBe(false);
  });

  it("选了就不报 —— 不管是哪个引擎的", () => {
    for (const config of [{ engine: "clone", voice: "v1" }, { engine: "edge", voice: "zh-CN-XiaoxiaoNeural" }]) {
      const a = analyzeWorkflow(node({ text: "念一句", ...config }), registry, fullCtx);
      const missing = (issuesAtLayer(a.issues, []).get("sp") ?? []).filter((i) => i.code === "required-missing");
      expect(missing, JSON.stringify(config)).toEqual([]);
    }
  });

  it("由数据边接上的也算填了", () => {
    // 上游算出一个音色 id 接过来 —— 那和手填是同一件事,不该报"没填"。
    const g = graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "sp", type: "synthesize_speech", config: { text: "念一句", voice: "" } },
      ],
      [
        { id: "e1", source: "start", target: "sp" },
        { id: "d1", source: "start", target: "sp", kind: "data", source_output: "params", target_input: "voice" },
      ],
    );
    const missing = (issuesAtLayer(analyzeWorkflow(g, registry, fullCtx).issues, []).get("sp") ?? []).filter(
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

  it("问题记在它真正所在的那一层;主流程上折到容器头上,钻进去挂在出问题的那个节点上", () => {
    // 此前一律改记到外层容器名下:钻进循环体一个角标都看不到,点清单也只能停在容器上。
    const a = analyzeWorkflow(withBody([{ id: "inner", type: "template", name: "拼一句", config: { template: "" } }]), registry, fullCtx);
    expect(a.issues).toEqual([
      expect.objectContaining({ nodeId: "inner", path: ["loop"], nodeName: "逐镜生成 › 拼一句", code: "required-missing" }),
    ]);
    const root = issuesAtLayer(a.issues, []);
    expect(root.get("inner")).toBeUndefined();
    expect(root.get("loop")).toHaveLength(1);
    expect(worstSeverity(root.get("loop") ?? [])).toBe("error");
    const inside = issuesAtLayer(a.issues, ["loop"]);
    expect(inside.get("inner")).toHaveLength(1);
    expect(inside.get("loop")).toBeUndefined();
  });

  it("体里再套一层:每一层都只看得见通往问题的那一个节点", () => {
    const nested = {
      nodes: [{ id: "deep", type: "template", config: { template: "" } }],
      edges: [],
    };
    const a = analyzeWorkflow(
      withBody([{ id: "inner-loop", type: "loop_foreach", config: { items: "{{loop.item}}", body: nested } }]),
      registry,
      fullCtx,
    );
    expect(a.issues).toContainEqual(expect.objectContaining({ nodeId: "deep", path: ["loop", "inner-loop"] }));
    expect([...issuesAtLayer(a.issues, []).keys()]).toEqual(["loop"]);
    expect([...issuesAtLayer(a.issues, ["loop"]).keys()]).toEqual(["inner-loop"]);
    expect([...issuesAtLayer(a.issues, ["loop", "inner-loop"]).keys()]).toEqual(["deep"]);
    //: 别的分支里的问题不挂在这一层。
    expect(issuesAtLayer(a.issues, ["elsewhere"]).size).toBe(0);
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

  /**
   * 体内认哪些名字,**按节点声明的 body_scope**,不再是「一律认 loop 与 input」。多认一个的代价
   * 不是"漏报一条"这么轻:子图体里的 `{{loop.item}}` 画布说能跑,后端启动前就拒;条件循环体里的
   * `{{input.x}}` 两边都放行,运行时安静地变成空串。
   */
  it.each([
    ["subgraph", "{{loop.item}}", "{{loop.item}}"],
    ["loop_while", "{{input.voice_id}}", "{{input.voice_id}}"],
  ])("%s 的体里引用它没有的作用域名要报", (type, template, ref) => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "box", type, config: { body: { nodes: [{ id: "inner", type: "template", config: { template } }], edges: [] } } },
        ],
        [{ id: "e1", source: "start", target: "box" }],
      ),
      registry,
      fullCtx,
    );
    expect(a.issues).toContainEqual(expect.objectContaining({ nodeId: "inner", path: ["box"], code: "stale-var", ref }));
    expect(a.runnable).toBe(false);
  });

  it("体里没有 start 不算缺开始节点", () => {
    // 循环体由外层驱动,它本来就没有 start。
    const a = analyzeWorkflow(withBody([{ id: "inner", type: "template", config: { template: "ok" } }]), registry, fullCtx);
    expect(a.issues.filter((i) => i.code === "missing-start")).toEqual([]);
  });
});

describe("节点类型不在目录里", () => {
  //: 插件没装、停用了、或工具没了,目录里就没有这种节点。后端跑到它报「未知的节点类型」——
  //: 此前清单全绿、画布上只剩一个裸的 `plugin.包.工具`,点了运行才知道。
  it("插件节点不可用是阻断问题,记在它自己那个节点上", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "p1", type: "plugin.comfy.upscale", config: {} },
        ],
        [{ id: "e1", source: "start", target: "p1" }],
      ),
      registry,
      fullCtx,
    );
    expect(a.issues).toContainEqual(expect.objectContaining({ nodeId: "p1", code: "unknown-type", severity: "error", nodeType: "plugin.comfy.upscale" }));
    expect(a.runnable).toBe(false);
  });

  it("目录里有的节点不报", () => {
    const a = analyzeWorkflow(graph([{ id: "start", type: "start", config: {} }]), registry, fullCtx);
    expect(a.issues.filter((i) => i.code === "unknown-type")).toEqual([]);
  });
});
