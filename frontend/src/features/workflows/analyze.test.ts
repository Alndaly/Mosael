import { describe, expect, it } from "vitest";

import {
  analyzeWorkflow,
  drivesDigitalHuman,
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
        config?: Record<string, { type?: string; required?: boolean; data_type?: string; default?: string; depends_on?: string; active_when?: Record<string, unknown>; one_of?: string; one_of_strict?: boolean }>;
        output_types?: Record<string, string>;
        body_scope?: Record<string, string[]>;
      }
    > = {
      start: { config: { params: { type: "object" } } },
      code: { config: { code: { type: "code", required: true }, input: { type: "object" } }, output_types: { output: "any" } },
      llm: {
        config: {
          prompt: { type: "template", required: true },
          profile_id: { type: "string" },
        },
        output_types: { text: "text", json: "json" },
      },
      // 提示词不在声明里标必填:要不要写由选中的模型说(见 AnalyzeContext.generationPromptMode)。
      ai_generate: {
        config: { provider: { type: "string", required: true }, prompt: { type: "template" }, consent: { type: "string" } },
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
      // 执行器两样都给就报错、不按顺序取(后端 one_of_strict):这一组照旧恰好一个,没有兜底。
      browser_upload: {
        config: {
          asset_id: { type: "template", one_of: "source", one_of_strict: true },
          file_path: { type: "template", one_of: "source", one_of_strict: true },
        },
      },
      // 选择器和文字恰好填一个 —— 除非前面填了的都只是引用 / 接了上游(运行时空了就取下一个,作兜底)。
      browser_click: {
        config: {
          selector: { type: "template", one_of: "target" },
          text: { type: "template", one_of: "target" },
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
    // 上传的素材 / 路径是 strict 组(后端 one_of_strict:两样都给上传就报错):前面接上游、后面写死也是两个,
    // 不放宽成兜底(放宽的那种见下面 one_of 兜底那一组)。
    expect(issuesOf(make({ file_path: "/tmp/x.mp4" }, "asset_id"))).toEqual([
      expect.objectContaining({ code: "one-of-both" }),
    ]);
    expect(issuesOf(make({ asset_id: "{{start.asset}}", file_path: "/tmp/x.mp4" })).filter((i) => i.code.startsWith("one-of"))).toEqual([
      expect.objectContaining({ code: "one-of-both" }),
    ]);
    expect(issuesOf(make({ asset_id: "a1" }, "file_path"))).toEqual([
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
        { id: "d1", source: "start", target: "sp", kind: "data", source_output: "voice", target_input: "voice" },
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
        { id: "start", type: "start", config: { params: { shots: "[]" } } },
        {
          id: "loop",
          type: "loop_foreach",
          name: "逐镜生成",
          config: { items: "{{start.shots}}", body: { nodes: inner, edges: [] } },
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

describe("代码字段里的 {{…}} 不是引用", () => {
  //: 代码不插值(后端 graph_rules.code_fields):那一段原样留在代码里。它不该被当成失效引用报错,
  //: 也不该悄悄放过 —— 提醒一句它不会被替换、上游的值要接到 input。
  it("提醒不会被替换,不报失效引用", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "c1", type: "code", config: { code: "output = '{{gone.text}}'" } },
        ],
        [{ id: "e1", source: "start", target: "c1" }],
      ),
      registry,
      fullCtx,
    );
    expect(a.issues).toContainEqual(expect.objectContaining({ nodeId: "c1", code: "code-template", severity: "warn", configKey: "code" }));
    expect(a.issues.filter((i) => i.code === "stale-var")).toEqual([]);
  });

  it("入参里的引用照常查失效", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "c1", type: "code", config: { code: "output = inputs['t']", input: { t: "{{gone.text}}" } } },
        ],
        [{ id: "e1", source: "start", target: "c1" }],
      ),
      registry,
      fullCtx,
    );
    expect(a.issues).toContainEqual(expect.objectContaining({ nodeId: "c1", code: "stale-var", configKey: "input" }));
    expect(a.issues.filter((i) => i.code === "code-template")).toEqual([]);
  });
});

describe("数字人生成的授权确认", () => {
  //: 挂了驱动音频(说话照片、对口型)就是数字人:生成漏斗没有「已取得授权」当场拒(genErr_digitalHumanNeedsConsent)。
  //: 此前检查器把这一格提成必填,就绪清单却全绿 —— 前面几步跑完、花了钱,才在这一步被拒。
  const genGraph = (config: Record<string, unknown>, edges: WorkflowGraph["edges"] = []) =>
    graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "gen", type: "ai_generate", config: { provider: "alibaba", model: "talk", prompt: "hi", ...config } },
      ],
      [{ id: "e1", source: "start", target: "gen" }, ...edges],
    );
  const consentMissing = (g: WorkflowGraph) =>
    analyzeWorkflow(g, registry, fullCtx).issues.some(
      (i) => i.nodeId === "gen" && i.code === "required-missing" && i.configKey === "consent" && i.severity === "error",
    );

  it("素材里挂了驱动音频、没确认授权:阻断", () => {
    expect(consentMissing(genGraph({ source_assets: ["a1:first_frame", "{{tts.asset_id}}:driving_audio"] }))).toBe(true);
  });

  it("直接给了驱动音频链接也算数字人", () => {
    expect(consentMissing(genGraph({ parameters: { driving_audio_url: "https://x/a.mp3" } }))).toBe(true);
  });

  it("确认过了、或者授权接了上游,不报", () => {
    expect(consentMissing(genGraph({ source_assets: ["a2:driving_audio"], consent: "yes" }))).toBe(false);
    expect(
      consentMissing(
        genGraph({ source_assets: ["a2:driving_audio"] }, [
          { id: "d1", source: "start", target: "gen", kind: "data", source_output: "ok", target_input: "consent" },
        ]),
      ),
    ).toBe(false);
  });

  it("不是数字人(没有驱动音频)不要求授权", () => {
    expect(consentMissing(genGraph({ source_assets: ["a1:first_frame"], parameters: { driving_audio_url: "  " } }))).toBe(false);
  });

  it("判据是一个纯函数,检查器和就绪清单同一份", () => {
    expect(drivesDigitalHuman("ai_generate", { source_assets: ["x:driving_audio"] })).toBe(true);
    expect(drivesDigitalHuman("llm", { source_assets: ["x:driving_audio"] })).toBe(false);
  });
});

describe("代码字段接了上游", () => {
  //: 后端运行前拦(wfErr_codeFieldBound):上游的值整段变成代码,和把 {{}} 拼进去是同一个注入。
  //: 此前就绪清单全绿,点了运行才 422。
  it("代码字段被数据边喂是阻断问题,指向那一格", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "llm-1", type: "llm", config: { prompt: "写段代码" } },
          { id: "c1", type: "code", inputs: ["code"], config: { code: "" } },
        ],
        [
          { id: "e1", source: "start", target: "llm-1" },
          { id: "d1", source: "llm-1", target: "c1", kind: "data", source_output: "text", target_input: "code" },
        ],
      ),
      registry,
      fullCtx,
    );
    expect(a.issues).toContainEqual(
      expect.objectContaining({ nodeId: "c1", code: "code-field-bound", severity: "error", configKey: "code" }),
    );
    expect(a.runnable).toBe(false);
  });

  it("上游接到 input 不报", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "llm-1", type: "llm", config: { prompt: "hi" } },
          { id: "c1", type: "code", inputs: ["input"], config: { code: "output = input" } },
        ],
        [
          { id: "e1", source: "start", target: "llm-1" },
          { id: "d1", source: "llm-1", target: "c1", kind: "data", source_output: "text", target_input: "input" },
        ],
      ),
      registry,
      fullCtx,
    );
    expect(a.issues.filter((i) => i.code === "code-field-bound")).toEqual([]);
  });
});

describe("引到开始节点的参数", () => {
  //: 后端运行前查(graph_rules._unresolved_reference_errors):`{{start.x}}` 和从开始节点拉出的数据边,
  //: 那个参数要在开始节点的 params 里。编辑器里的运行不带参数,所以没声明的就是一个运行时的空串 ——
  //: 下游拿着空提示词去付费生成。此前画布全绿。
  const make = (startConfig: Record<string, unknown>, prompt: string, edges: WorkflowGraph["edges"] = []) =>
    graph(
      [
        { id: "start", type: "start", config: startConfig },
        { id: "llm-1", type: "llm", config: { prompt, profile_id: "p1" } },
      ],
      [{ id: "e1", source: "start", target: "llm-1" }, ...edges],
    );
  const missing = (g: WorkflowGraph) =>
    analyzeWorkflow(g, registry, fullCtx)
      .issues.filter((i) => i.code === "start-param-missing")
      .map((i) => [i.nodeId, i.configKey, i.ref, i.severity]);

  it("引用了开始节点没声明的参数:阻断,说清是哪一个", () => {
    expect(missing(make({ params: { topic: "" } }, "写 {{start.topic}} 和 {{start.tone}}"))).toEqual([
      ["llm-1", "prompt", "{{start.tone}}", "error"],
    ]);
  });

  it("从开始节点拉出的数据边,参数没声明也报在接它的那一格上", () => {
    expect(
      missing(
        make({ params: {} }, "", [
          { id: "d1", source: "start", target: "llm-1", kind: "data", source_output: "topic", target_input: "prompt" },
        ]),
      ),
    ).toEqual([["llm-1", "prompt", "{{start.topic}}", "error"]]);
  });

  it("点名为必填、但 params 里没有的参数照样报:编辑器里的运行不带参数", () => {
    expect(missing(make({ params: {}, required_params: "topic" }, "{{start.topic}}"))).toEqual([
      ["llm-1", "prompt", "{{start.topic}}", "error"],
    ]);
  });

  it("声明了的(哪怕值是空的)不报;不是开始节点的引用不归这条管", () => {
    expect(missing(make({ params: { topic: "" } }, "{{start.topic}}"))).toEqual([]);
    expect(missing(make({ params: {} }, "{{gone.text}}"))).toEqual([]);
  });
});

describe("循环体 / 子图本身的几条规矩(与后端 validate_body_graph 同一份)", () => {
  const boxed = (type: string, config: Record<string, unknown>) =>
    graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "box", type, name: "逐镜", config },
      ],
      [{ id: "e1", source: "start", target: "box" }],
    );
  const issuesOf = (g: WorkflowGraph) => analyzeWorkflow(g, registry, fullCtx).issues;

  it("体是空的(没建、或一个节点都没有):阻断,记在容器自己身上", () => {
    //: 后端运行前拒「循环体不能为空」。刚拖出来的循环节点就是这样 —— 此前清单全绿。
    for (const config of [{ items: "a" }, { items: "a", body: { nodes: [], edges: [] } }]) {
      expect(issuesOf(boxed("loop_foreach", config))).toContainEqual(
        expect.objectContaining({ nodeId: "box", path: [], code: "body-empty", severity: "error", configKey: "body" }),
      );
    }
    expect(
      issuesOf(boxed("loop_foreach", { items: "a", body: { nodes: [{ id: "t", type: "template", config: { template: "x" } }], edges: [] } }))
        .filter((i) => i.code === "body-empty"),
    ).toEqual([]);
  });

  it("体里放「输出」节点:阻断 —— 工作流的输出只在最外层算数", () => {
    const a = issuesOf(
      boxed("subgraph", { body: { nodes: [{ id: "out", type: "output", config: {} }], edges: [] } }),
    );
    expect(a).toContainEqual(expect.objectContaining({ nodeId: "out", path: ["box"], code: "output-in-body", severity: "error" }));
    // 最外层的输出节点不归这条管
    expect(issuesOf(graph([{ id: "start", type: "start", config: {} }, { id: "out", type: "output", config: {} }])).filter((i) => i.code === "output-in-body")).toEqual([]);
  });

  it("{{loop.不存在}}:作用域名对了、字段不在它提供的那几个里,阻断并说清有哪些", () => {
    const a = issuesOf(
      boxed("loop_foreach", {
        items: "a",
        body: { nodes: [{ id: "t", type: "template", config: { template: "{{loop.item.x}} {{loop.itme}}" } }], edges: [] },
        output: "{{loop.idx}}",
      }),
    );
    const missing = a.filter((i) => i.code === "scope-field-missing");
    expect(missing).toHaveLength(2);
    expect(missing).toContainEqual(
      expect.objectContaining({ nodeId: "t", path: ["box"], configKey: "template", ref: "{{loop.itme}}", available: ["loop.item", "loop.index"] }),
    );
    expect(missing).toContainEqual(expect.objectContaining({ nodeId: "box", path: [], configKey: "output", ref: "{{loop.idx}}" }));
    // 字段来自配置的作用域(`*inputs`)只有运行时知道,不判;体里恰好有个节点叫 loop 时它就是那个节点。
    expect(
      issuesOf(
        boxed("loop_foreach", {
          items: "a",
          body: { nodes: [{ id: "t", type: "template", config: { template: "{{input.whatever}}" } }], edges: [] },
        }),
      ).filter((i) => i.code === "scope-field-missing"),
    ).toEqual([]);
  });
});

describe("one_of 里前面的是引用、最后一个是字面量:兜底,不算填了两个", () => {
  //: 运行时按声明顺序取第一个非空值(与后端 graph_rules.one_of_errors 同一条):上游给了选择器就用它,
  //: 给的是空就退到文字。前面那格只是一条引用 / 一条数据边时,它在运行时可能是空的 —— 后面的字面量是兜底。
  const click = (config: Record<string, unknown>, bound?: string) =>
    graph(
      [
        { id: "start", type: "start", config: {} },
        { id: "up", type: "llm", config: { prompt: "hi", profile_id: "p1" } },
        { id: "click", type: "browser_click", config },
      ],
      [
        { id: "e1", source: "start", target: "up" },
        { id: "e2", source: "up", target: "click" },
        ...(bound ? [{ id: "d", source: "up", target: "click", kind: "data", source_output: "text", target_input: bound }] : []),
      ] as WorkflowGraph["edges"],
    );
  const both = (g: WorkflowGraph) =>
    analyzeWorkflow(g, registry, fullCtx).issues.filter((i) => i.nodeId === "click" && i.code === "one-of-both");

  it("选择器是 {{x.sel}}、文字是字面量:不报", () => {
    expect(both(click({ selector: "{{up.sel}}", text: "提交" }))).toEqual([]);
  });

  it("两个都是字面量:报", () => {
    expect(both(click({ selector: "#submit", text: "提交" }))).toEqual([
      expect.objectContaining({ severity: "error", group: ["selector", "text"] }),
    ]);
  });

  it("选择器接了数据边、文字是字面量:不报", () => {
    expect(both(click({ text: "提交" }, "selector"))).toEqual([]);
  });

  it("引用里夹着别的字、或者字面量在前引用在后:照样报", () => {
    expect(both(click({ selector: "#{{up.sel}}", text: "提交" }))).toHaveLength(1);
    expect(both(click({ selector: "#submit", text: "{{up.text}}" }))).toHaveLength(1);
  });
});

describe("没接进流程的节点被引用(和后端运行前那一道同一个判据)", () => {
  const ofNode = (a: ReturnType<typeof analyzeWorkflow>, id: string, path: string[] = []) =>
    a.issues.filter((issue) => issue.nodeId === id && issue.path.join("/") === path.join("/"));

  it("会跑的节点引用了它:被引用的那个标 error,点名谁引用、怎么引用;不能运行", () => {
    //: 「可用的 3D 道具」的现场:一条连线都没有,只靠布景提示词里的引用挂着,引擎每次都跳过它。
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "props", type: "template", name: "可用的 3D 道具", config: { template: "桌子" } },
          { id: "set", type: "template", name: "布景", config: { template: "道具:{{props.text}}" } },
        ],
        [{ id: "e1", source: "start", target: "set" }],
      ),
      registry,
      fullCtx,
    );
    expect(ofNode(a, "props")).toEqual([
      expect.objectContaining({ code: "unwired-referenced", severity: "error", referencedBy: ["布景"], refs: ["{{props.text}}"] }),
    ]);
    expect(a.runnable).toBe(false);
  });

  it("没人引用的孤立节点:照旧只是提醒,不挡运行", () => {
    const a = analyzeWorkflow(
      graph([
        { id: "start", type: "start", config: {} },
        { id: "stray", type: "template", config: { template: "x" } },
      ]),
      registry,
      fullCtx,
    );
    expect(ofNode(a, "stray")).toEqual([expect.objectContaining({ code: "disconnected", severity: "warn" })]);
    expect(a.runnable).toBe(true);
  });

  it("数据边也是引用:从不会跑的节点接过来的值照样拦", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "props", type: "template", config: { template: "桌子" } },
          { id: "set", type: "template", config: { template: "" } },
        ],
        [
          { id: "e1", source: "start", target: "set" },
          { id: "d1", source: "props", target: "set", kind: "data", source_output: "text", target_input: "template" },
        ],
      ),
      registry,
      fullCtx,
    );
    expect(ofNode(a, "props")).toEqual([expect.objectContaining({ code: "unwired-referenced", refs: ["{{props.text}}"] })]);
  });

  it("被引用的在条件分支里:可能跑可能不跑,不标", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "c", type: "condition", config: {} },
          { id: "voice", type: "template", config: { template: "画外音" } },
          { id: "join", type: "template", config: { template: "[{{voice.text}}]" } },
        ],
        [
          { id: "e1", source: "start", target: "c" },
          { id: "e2", source: "c", target: "voice", source_handle: "true" },
          { id: "e3", source: "start", target: "join" },
        ],
      ),
      registry,
      fullCtx,
    );
    expect(a.issues.filter((issue) => issue.code === "unwired-referenced" || issue.code === "disconnected")).toEqual([]);
  });

  it("有控制边只看控制边:控制边来自不会跑的节点,另有来自开始节点的数据边 —— 也算不会跑", () => {
    //: 此前「从开始节点沿任意连线走得到」就算接上了;引擎却只看控制边,它每次都被跳过。
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: { params: { topic: "猫" } } },
          { id: "p", type: "template", config: { template: "x" } },
          { id: "q", type: "template", config: { template: "" } },
        ],
        [
          { id: "e1", source: "p", target: "q" },
          { id: "d1", source: "start", target: "q", kind: "data", source_output: "topic", target_input: "template" },
        ],
      ),
      registry,
      fullCtx,
    );
    expect(ofNode(a, "q").map((issue) => issue.code)).toEqual(["disconnected"]);
  });

  it("循环体里没有入边的根就是入口:被引用不标,也不算没接上", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          {
            id: "loop",
            type: "loop_foreach",
            config: {
              items: "a",
              body: {
                nodes: [
                  { id: "style", type: "template", config: { template: "胶片感" } },
                  { id: "shot", type: "template", config: { template: "{{loop.item}} {{style.text}}" } },
                ],
                edges: [],
              },
            },
          },
        ],
        [{ id: "e1", source: "start", target: "loop" }],
      ),
      registry,
      fullCtx,
    );
    expect(a.issues).toEqual([]);
  });

  it("循环节点的 inputs 在外层解析:引用了外层没接进流程的节点,标在外层那个节点上;output 属于体内,不算", () => {
    const a = analyzeWorkflow(
      graph(
        [
          { id: "start", type: "start", config: {} },
          { id: "p", type: "template", config: { template: "x" } },
          {
            id: "loop",
            type: "loop_foreach",
            config: {
              items: "a",
              inputs: { style: "{{p.text}}" },
              output: "{{p.text}}",
              body: { nodes: [{ id: "p", type: "template", config: { template: "{{input.style}}" } }], edges: [] },
            },
          },
        ],
        [{ id: "e1", source: "start", target: "loop" }],
      ),
      registry,
      fullCtx,
    );
    expect(ofNode(a, "p")).toEqual([expect.objectContaining({ code: "unwired-referenced", referencedBy: ["loop_foreach"] })]);
    expect(ofNode(a, "p", ["loop"])).toEqual([]);
  });
});
