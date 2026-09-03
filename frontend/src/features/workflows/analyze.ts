import type { WorkflowGraph } from "@/api/client";

/**
 * 工作流"就绪度"分析:纯函数,单一事实来源,同时喂给画布告警角标、
 * 运行前 checklist、以及节点属性面板的失效引用标红。无 React、无 i18n —
 * 只产出结构化 issue,文案由调用方按 code 翻译(见 messages.ts wfIssue*)。
 */

export type IssueSeverity = "error" | "warn";

export type IssueCode =
  | "missing-start" // 工作流没有开始节点
  | "required-missing" // 必填字段为空
  | "disconnected" // 非 start 节点无法从 start 到达
  | "stale-var" // 配置里引用了已删除的节点
  | "no-providers" // LLM 节点但一个供应商都没配
  | "provider-missing" // LLM 绑定的供应商配置已被删
  | "gen-provider-unconfigured" // AI 生成选的服务商没配密钥
  | "type-mismatch"; // 数据边:上游输出类型与目标输入期望类型不兼容(软提示)

export interface NodeIssue {
  nodeId: string;
  nodeName: string;
  nodeType: string;
  severity: IssueSeverity;
  code: IssueCode;
  /** issue 关联的配置字段名(必填缺失 / 失效引用 / 类型不匹配所在字段)。 */
  configKey?: string;
  /** stale-var:失效的完整引用,如 "{{llm-1.text}}"。 */
  ref?: string;
  /** type-mismatch:期望/实际类型,拼进文案。 */
  expected?: DataType;
  actual?: DataType;
}

/** 软数据类型:仅用于就绪检查提示,不阻断运行(模板终究是字符串插值)。 */
export type DataType = "text" | "asset" | "sequence" | "number" | "json" | "any";

const DATA_TYPES = new Set<DataType>(["text", "asset", "sequence", "number", "json", "any"]);

function normalizeDataType(value: unknown): DataType {
  const declared = String(value ?? "").trim() as DataType;
  return DATA_TYPES.has(declared) ? declared : "any";
}

/**
 * 一个输入字段**装的是什么** —— 素材?时间线?还是随便什么值。
 *
 * **权威在后端**:节点声明里每个配置字段带着 `data_type`(见 domain/workflows.config_data_type,
 * 按 asset_id / sequence_id 这套命名自动推)。这里只负责读。
 *
 * 此前这是前端自己抄的一张表,后果是三件事一起坏:「素材」节点本身就漏了(它整个存在的意义
 * 就是指向一份素材,却拿不到素材选择器,用户只能手打一串十六进制)、asset_tag / asset_update /
 * browser_upload 也漏了、而**插件节点永远不可能被那张表覆盖** —— 它们是运行时才知道的。
 * 加一种节点忘了补表不会报错,只是安静地少了选择器和类型校验。
 */
export function fieldDataType(spec: ConfigSpecLike | null | undefined): DataType {
  return normalizeDataType((spec as { data_type?: unknown } | null | undefined)?.data_type);
}

/** 从注册表里取某个字段的类型。有 registry 在手时用它,省得调用方自己翻两层。 */
export function inputType(registry: RegistryLike, nodeType: string, key: string): DataType {
  const config = registry.get(nodeType)?.config as Record<string, ConfigSpecLike> | undefined;
  return fieldDataType(config?.[key]);
}

/**
 * 从运行时节点注册表读取输出类型。
 *
 * 节点可以来自内置实现或运行时插件，前端不能凭节点名维护第二张映射表；未声明或未知的类型
 * 退回 `any`，保持软类型检查不误报。
 */
export function outputType(registry: RegistryLike, nodeType: string, output: string): DataType {
  return normalizeDataType(registry.get(nodeType)?.output_types?.[output]);
}

/** 软兼容:any 通配;text 槽接受一切(都能字符串化);同类型兼容;否则不兼容。 */
export function typesCompatible(source: DataType, target: DataType): boolean {
  if (target === "any" || source === "any" || target === "text") return true;
  return source === target;
}

export interface AnalyzeContext {
  /** 已存在的供应商配置 id。 */
  providerIds: Set<string>;
  providersLoaded: boolean;
  /** 已配置且启用 image/video 能力的生成供应商名。 */
  configuredGenProviders: Set<string>;
  genProvidersLoaded: boolean;
}

interface ConfigSpecLike {
  type?: string;
  required?: boolean;
  /** 这个字段装的是什么(素材/时间线/…)。**后端推好一起发过来**,见 domain/workflows。 */
  data_type?: string;
}

interface NodeMetaLike {
  // registry 的 config 值在 OpenAPI 里是 unknown;取用时按 ConfigSpecLike 收窄。
  config?: Record<string, unknown>;
  /** 每个输出承载的数据类型，由后端节点注册表统一声明。 */
  output_types?: Record<string, string>;
}

export interface RegistryLike {
  get(type: string): NodeMetaLike | undefined;
}

const VAR_RE = /\{\{\s*([\w.-]+)\s*\}\}/g;

// 内嵌子图节点(循环体 / subgraph):body/output/condition 引用的是子作用域({{loop.*}} / {{input.*}})
// 或**内部**节点,不在顶层解析,顶层失效检查要跳过它们(与后端 NESTED_BODY_TYPES / RAW_KEYS 对齐)。
/** 选一个生成模型就同时填上这三项 —— 就绪检查里当作一条。 */
const GENERATE_MODEL_KEYS = new Set(["provider", "model", "kind"]);

const NESTED_BODY_TYPES = new Set(["loop_foreach", "loop_while", "subgraph"]);
const NESTED_BODY_RAW_KEYS = new Set(["body", "output", "condition"]);

/** 从任意配置值里抽出 `{{id.output}}` 引用,返回 [{ ref, sourceId }]。 */
export function extractRefs(value: unknown): Array<{ ref: string; sourceId: string }> {
  if (typeof value !== "string" || !value.includes("{{")) return [];
  const out: Array<{ ref: string; sourceId: string }> = [];
  for (const match of value.matchAll(VAR_RE)) {
    const inner = match[1];
    const sourceId = inner.split(".")[0];
    if (sourceId) out.push({ ref: `{{${inner}}}`, sourceId });
  }
  return out;
}

function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return value.trim() === "";
  if (typeof value === "object") return Object.keys(value as object).length === 0;
  return false;
}

/** 从 start 节点出发能到达的节点集合(顺着连线方向 BFS)。 */
function reachableFromStart(graph: WorkflowGraph): Set<string> {
  const start = graph.nodes.find((n) => n.type === "start");
  const reached = new Set<string>();
  if (!start) return reached;
  const adjacency = new Map<string, string[]>();
  for (const edge of graph.edges) {
    adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
  }
  const queue = [start.id];
  while (queue.length) {
    const current = queue.pop()!;
    if (reached.has(current)) continue;
    reached.add(current);
    queue.push(...(adjacency.get(current) ?? []));
  }
  return reached;
}

export interface Analysis {
  issues: NodeIssue[];
  byNode: Map<string, NodeIssue[]>;
  /** 每个节点的最高严重度,画布角标用。 */
  severityByNode: Map<string, IssueSeverity>;
  errorCount: number;
  warnCount: number;
  /** 有 error 时禁止运行。 */
  runnable: boolean;
}

export function analyzeWorkflow(
  graph: WorkflowGraph,
  registry: RegistryLike,
  ctx: AnalyzeContext,
): Analysis {
  const issues: NodeIssue[] = [];
  const nodeIds = new Set(graph.nodes.map((n) => n.id));
  const reachable = reachableFromStart(graph);
  const hasStart = graph.nodes.some((n) => n.type === "start");
  if (!hasStart) {
    issues.push({
      nodeId: "__workflow__",
      nodeName: "Workflow",
      nodeType: "workflow",
      severity: "error",
      code: "missing-start",
    });
  }
  // 被数据边喂的输入,即便字面量为空也算已满足(与后端 validate_graph 同源)。
  const dataBound = new Set(
    graph.edges
      .filter((edge) => edge.kind === "data" && edge.target_input)
      .map((edge) => `${edge.target}:${edge.target_input}`),
  );

  for (const node of graph.nodes) {
    const nodeName = node.name || node.type;
    const meta = registry.get(node.type);
    const config = (node.config ?? {}) as Record<string, unknown>;
    const push = (severity: IssueSeverity, code: IssueCode, extra?: Partial<NodeIssue>) =>
      issues.push({ nodeId: node.id, nodeName, nodeType: node.type, severity, code, ...extra });

    // 必填字段 + 失效引用(逐字段)
    for (const [key, rawSpec] of Object.entries(meta?.config ?? {})) {
      const spec = (rawSpec ?? {}) as ConfigSpecLike;
      if (spec.required && isEmpty(config[key]) && !dataBound.has(`${node.id}:${key}`)) {
        // AI 生成节点的 provider/model/kind 是**一次选择**的三个产物(选一个生成模型即全部填上),
        // 分开报会变成三条待办、指向三个界面上根本不存在的字段名。归成一条,指向那个选择器。
        if (node.type === "ai_generate" && GENERATE_MODEL_KEYS.has(key)) {
          if (key === "model") push("error", "required-missing", { configKey: "model" });
        } else {
          push("error", "required-missing", { configKey: key });
        }
      }
      // 子图/循环体的 body/output/condition 引用子作用域或内部节点,顶层不做失效检查(否则误报)。
      if (NESTED_BODY_TYPES.has(node.type) && NESTED_BODY_RAW_KEYS.has(key)) continue;
      for (const { ref, sourceId } of extractRefs(config[key])) {
        // start 的 *params 通配前缀不算节点 id;引用不存在的节点即失效。
        if (!nodeIds.has(sourceId)) push("error", "stale-var", { configKey: key, ref });
      }
    }

    // 绑定校验(与属性面板 bindingNotice 同源)
    if (node.type === "llm") {
      if (ctx.providersLoaded && ctx.providerIds.size === 0) push("warn", "no-providers");
      const pid = config.profile_id;
      if (typeof pid === "string" && pid && ctx.providersLoaded && !ctx.providerIds.has(pid))
        push("error", "provider-missing", { configKey: "profile_id" });
    }
    if (node.type === "ai_generate") {
      const provider = config.provider;
      if (
        typeof provider === "string" &&
        provider &&
        ctx.genProvidersLoaded &&
        !ctx.configuredGenProviders.has(provider)
      )
        push("error", "gen-provider-unconfigured", { configKey: "provider" });
    }

    // 断连:有 start 时,非 start 节点却到不了 → 游离
    if (hasStart && node.type !== "start" && !reachable.has(node.id)) push("warn", "disconnected");
  }

  // 数据边:软类型校验(不阻断)。目标输入是强类型槽、上游输出类型又对不上时给提醒。
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  for (const edge of graph.edges) {
    if (edge.kind !== "data" || !edge.source_output || !edge.target_input) continue;
    const source = nodeById.get(edge.source);
    const target = nodeById.get(edge.target);
    if (!source || !target) continue;
    const actual = outputType(registry, source.type, edge.source_output);
    const expected = inputType(registry, target.type, edge.target_input);
    if (!typesCompatible(actual, expected)) {
      issues.push({
        nodeId: target.id,
        nodeName: target.name || target.type,
        nodeType: target.type,
        severity: "warn",
        code: "type-mismatch",
        configKey: edge.target_input,
        expected,
        actual,
      });
    }
  }

  const byNode = new Map<string, NodeIssue[]>();
  const severityByNode = new Map<string, IssueSeverity>();
  for (const issue of issues) {
    byNode.set(issue.nodeId, [...(byNode.get(issue.nodeId) ?? []), issue]);
    if (issue.severity === "error" || !severityByNode.has(issue.nodeId)) {
      severityByNode.set(issue.nodeId, issue.severity === "error" ? "error" : severityByNode.get(issue.nodeId) ?? "warn");
    }
  }
  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warnCount = issues.length - errorCount;
  return { issues, byNode, severityByNode, errorCount, warnCount, runnable: errorCount === 0 };
}
