import type { WorkflowGraph } from "@/api/client";

import { isWorkflowFieldActive } from "@/features/nodeForms/fieldActivation";
import { fieldDataType, normalizeDataType, type DataType } from "@/features/nodeForms/fieldTypes";

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

/**
 * 输出接点在人机界面上的名字。**只有这一处取法。**
 *
 * 没声明就给空串,由调用方决定退回什么(接点退回稳定 key 并用 mono 显示,产出面板退回 key)。
 * 前端不编第二套名字:同一个输出在接点上叫「人声」、在产出里叫 `vocals_asset_id`,是同一件
 * 东西说两种话 —— 而画布上那根线连的就是它。
 */
export function outputLabel(registry: RegistryLike, nodeType: string, output: string): string {
  return String(registry.get(nodeType)?.output_labels?.[output] ?? "").trim();
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
  default?: unknown;
  active_when?: Record<string, unknown | unknown[]>;
  /** 这个字段装的是什么(素材/时间线/…)。**后端推好一起发过来**,见 domain/workflows。 */
  data_type?: string;
}

interface NodeMetaLike {
  // registry 的 config 值在 OpenAPI 里是 unknown;取用时按 ConfigSpecLike 收窄。
  config?: Record<string, unknown>;
  /** 「这几个字段里至少要有一个」。**由后端声明**,不在这里按节点名写死 —— 见下面的说明。 */
  /** 每个输出承载的数据类型，由后端节点注册表统一声明。 */
  output_types?: Record<string, string>;
  /** 每个输出在人机界面上的名字(「人声」「背景音」),同样由后端声明并按语言发下来。 */
  output_labels?: Record<string, string>;
  /** 内嵌子图节点(循环 / 子图)体内看得见什么:作用域名 → 字段。**由后端声明**(NODE_TYPES 的 body_scope)。 */
  body_scope?: Record<string, string[]>;
}

export interface RegistryLike {
  get(type: string): NodeMetaLike | undefined;
}

const VAR_RE = /\{\{\s*([\w.-]+)\s*\}\}/g;

/** 选一个生成模型就同时填上这三项 —— 就绪检查里当作一条。 */
const GENERATE_MODEL_KEYS = new Set(["provider", "model", "kind"]);

// 内嵌子图节点(循环体 / subgraph):body/output/condition 引用的是子作用域({{loop.*}} / {{input.*}})
// 或**内部**节点,不在顶层解析,顶层失效检查要跳过它们(与后端 NESTED_BODY_RAW_KEYS 对齐)。
const NESTED_BODY_RAW_KEYS = new Set(["body", "output", "condition"]);

/**
 * 这个节点的体内看得见哪些作用域名;不是内嵌子图节点就是空表。
 *
 * **后端说了算**:执行器给体播种的就是这几个名字,后端校验也按它判。此前这里自己写死
 * 「循环和子图一律认 loop 与 input」—— 子图体里的 `{{loop.item}}` 画布说能跑,后端却拒绝;
 * 条件循环体里的 `{{input.x}}` 两边都放行,运行时安静地变成空串。
 */
export function bodyScope(registry: RegistryLike, nodeType: string): string[] {
  return Object.keys(registry.get(nodeType)?.body_scope ?? {});
}

/** 这些字段属于内嵌图自己的作用域，父图不能拿自己的节点表去判定其中的引用。 */
export function isNestedScopeConfig(registry: RegistryLike, nodeType: string, configKey: string): boolean {
  return bodyScope(registry, nodeType).length > 0 && NESTED_BODY_RAW_KEYS.has(configKey);
}

/** 从任意配置值里抽出 `{{id.output}}` 引用,返回 [{ ref, sourceId }]。 */
export function extractRefs(value: unknown): Array<{ ref: string; sourceId: string }> {
  if (Array.isArray(value)) return value.flatMap(extractRefs);
  if (value && typeof value === "object") return Object.values(value).flatMap(extractRefs);
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

/**
 * 收集一层图里的问题。
 *
 * **循环体和子图要一起收。** 此前只走顶层,于是 `loop_foreach` / `subgraph` 体里的节点
 * 从没被检查过 —— 而最贵的那几步恰恰住在里面(示范模板的整个"逐镜生成"都在循环体里)。
 * 表现是画布全绿、点了运行、前面几步跑完花了钱,才在循环里第一镜上失败。
 *
 * `scopeExtras` 是这一层**注入的变量名**:体内的 `{{loop.item.x}}` 和 `{{input.y}}` 引用的
 * 不是节点,是作用域给的东西。不把它们算进来的话,递归下去会把每一条正常引用都报成失效;
 * 多算一个的话,引用了一个运行时根本不存在的名字也会被放行。所以只认节点声明的那几个。
 *
 * `insideName` 有值时,这一层的问题**记在外层那个节点头上** —— 画布上只画得出顶层节点,
 * 给一个画不出来的 id 挂角标等于这条问题没人看得见。名字里带上路径("逐镜生成 › 合成口播"),
 * 于是点开哪一个仍然一目了然。
 */
function collect(
  graph: WorkflowGraph,
  registry: RegistryLike,
  ctx: AnalyzeContext,
  issues: NodeIssue[],
  scopeExtras: ReadonlySet<string> = new Set(),
  attributeTo = "",
  insideName = "",
): void {
  const nodeIds = new Set([...graph.nodes.map((n) => n.id), ...scopeExtras]);
  const reachable = reachableFromStart(graph);
  // 「没有开始节点」只对顶层成立 —— 循环体本来就没有 start,它由外层驱动。
  const hasStart = graph.nodes.some((n) => n.type === "start");
  if (!hasStart && !attributeTo) {
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
      issues.push({
        nodeId: attributeTo || node.id,
        nodeName: insideName ? `${insideName} › ${nodeName}` : nodeName,
        nodeType: node.type,
        severity,
        code,
        ...extra,
      });

    // 必填字段 + 失效引用(逐字段)
    const fieldSpecs = (meta?.config ?? {}) as Record<string, ConfigSpecLike>;
    for (const [key, rawSpec] of Object.entries(fieldSpecs)) {
      const spec = (rawSpec ?? {}) as ConfigSpecLike;
      if (!isWorkflowFieldActive(spec, config, fieldSpecs)) continue;
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
      if (isNestedScopeConfig(registry, node.type, key)) continue;
      for (const { ref, sourceId } of extractRefs(config[key])) {
        // start 的 *params 通配前缀不算节点 id;引用不存在的节点即失效。
        if (!nodeIds.has(sourceId)) push("error", "stale-var", { configKey: key, ref });
      }
    }

    // 往里走一层。体里的节点和外面一样会缺必填、会引用不存在的东西 —— 只是此前没人看。
    const body = (node.config as Record<string, unknown> | undefined)?.body;
    if (body && typeof body === "object" && Array.isArray((body as WorkflowGraph).nodes)) {
      collect(
        body as WorkflowGraph,
        registry,
        ctx,
        issues,
        new Set(bodyScope(registry, node.type)),
        attributeTo || node.id,
        insideName ? `${insideName} › ${nodeName}` : nodeName,
      );
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
        nodeId: attributeTo || target.id,
        nodeName: insideName
          ? `${insideName} › ${target.name || target.type}`
          : target.name || target.type,
        nodeType: target.type,
        severity: "warn",
        code: "type-mismatch",
        configKey: edge.target_input,
        expected,
        actual,
      });
    }
  }

}

export function analyzeWorkflow(
  graph: WorkflowGraph,
  registry: RegistryLike,
  ctx: AnalyzeContext,
): Analysis {
  const issues: NodeIssue[] = [];
  collect(graph, registry, ctx, issues);

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
