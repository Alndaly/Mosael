import type { WorkflowGraph } from "@/api/client";

import { isWorkflowFieldActive, oneOfGroups } from "@/features/nodeForms/fieldActivation";
import { fieldDataType, normalizeDataType, type DataType } from "@/features/nodeForms/fieldTypes";
import type { PromptMode } from "@/lib/generationCapabilities";
import { bodyKey, declaredFieldNames, type ScopePath } from "@/features/workflows/scope";
import { readSourceAssets } from "@/features/workflows/sourceAssetLines";

/**
 * 工作流"就绪度"分析:纯函数,单一事实来源,同时喂给画布告警角标、
 * 运行前 checklist、以及节点属性面板的失效引用标红。无 React、无 i18n —
 * 只产出结构化 issue,文案由调用方按 code 翻译(见 messages.ts wfIssue*)。
 */

export type IssueSeverity = "error" | "warn";

export type IssueCode =
  | "missing-start" // 工作流没有开始节点
  | "required-missing" // 必填字段为空
  | "one-of-both" // 同组(one_of)的字段填了不止一个
  | "one-of-missing" // 同组(one_of)的字段一个都没填
  | "disconnected" // 非 start 节点无法从 start 到达
  | "stale-var" // 配置里引用了已删除的节点
  | "start-param-missing" // 引到开始节点的参数({{start.x}} 或从它拉出的数据边),开始节点没声明
  | "no-providers" // LLM 节点但一个供应商都没配
  | "provider-missing" // LLM 绑定的供应商配置已被删
  | "gen-provider-unconfigured" // AI 生成选的服务商下没有可用的生成模型
  | "type-mismatch" // 数据边:上游输出类型与目标输入期望类型不兼容(软提示)
  | "code-template" // 代码字段里写了 {{…}}:代码不插值,那一段不会被替换(软提示)
  | "code-field-bound" // 代码字段接了数据边:上游的值整段变成代码,后端运行前拒(wfErr_codeFieldBound)
  | "unknown-type"; // 节点类型不在目录里:提供它的插件没装 / 停用了 / 工具已不存在

export interface NodeIssue {
  /** 问题所在的那个节点 —— **在它自己那一层里**的 id(体里的 id 和主流程是两套命名空间)。 */
  nodeId: string;
  /** 这个节点住在哪一层:从主流程往里经过的容器节点 id,`[]` 是主流程(同 scope.ts 的 ScopePath)。 */
  path: ScopePath;
  /** 给人读的名字。体里的带上路径(「逐镜生成 › 合成口播」)—— 就绪清单是整张图的,得说清在哪一层。 */
  nodeName: string;
  nodeType: string;
  severity: IssueSeverity;
  code: IssueCode;
  /** issue 关联的配置字段名(必填缺失 / 失效引用 / 类型不匹配所在字段)。 */
  configKey?: string;
  /** one-of-*:那一组的全部字段名(声明顺序)。 */
  group?: string[];
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
  /** LLM 节点能用的连接 id(见 bindingReadiness.chatProfileIds)。 */
  chatProfileIds: Set<string>;
  chatProfilesLoaded: boolean;
  /** 有可用生成模型的服务商(见 bindingReadiness.generationVendors)。 */
  generationVendors: Set<string>;
  generationModelsLoaded: boolean;
  /**
   * AI 生成节点选中的那个模型对提示词的要求(描述符的 `prompt`,见 lib/generationCapabilities.promptMode)。
   * 提示词不再在节点声明里标必填 —— 放大这类模型不收提示词,标了就永远过不了检查;所以「空着算不算
   * 缺」由这里按模型说。不给(模型清单还没拉到)就按 required,和以前一样拦。
   */
  generationPromptMode?: (config: Record<string, unknown>) => PromptMode;
}

interface ConfigSpecLike {
  type?: string;
  required?: boolean;
  default?: unknown;
  active_when?: Record<string, unknown | unknown[]>;
  one_of?: string;
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

/**
 * 这一格是不是代码(`"type": "code"`)。代码字段**不插值**(后端 graph_rules.code_fields):里面的 `{{…}}`
 * 原样留在代码里,不是引用 —— 不算依赖、不查失效,也不能接上游(上游的值要接到节点的 input)。
 */
export function isCodeConfig(registry: RegistryLike, nodeType: string, configKey: string): boolean {
  return (registry.get(nodeType)?.config?.[configKey] as ConfigSpecLike | undefined)?.type === "code";
}

/**
 * 这个生成节点是不是数字人(说话照片、对口型):挂了一段驱动音频。授权确认是它跑不跑得了的前提 ——
 * 生成漏斗没它当场拒(genErr_digitalHumanNeedsConsent)。
 *
 * 判据和后端 generation.operations.is_digital_human_request 同一条:按素材角色认,或直接给了驱动音频链接。
 * 检查器(把授权提到第一屏、标必填)和就绪清单(空着就阻断)读的都是这一个函数 —— 此前只有检查器在判,
 * 清单全绿,前面几步跑完、花了钱才在这一步被拒。
 */
export function drivesDigitalHuman(nodeType: string, config: Record<string, unknown>): boolean {
  if (nodeType !== "ai_generate") return false;
  if (readSourceAssets(config.source_assets).some((line) => line.role === "driving_audio")) return true;
  const parameters = (config.parameters ?? {}) as Record<string, unknown>;
  return Boolean(String(parameters.driving_audio_url ?? "").trim());
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

/** 引用里节点后面那一段(`{{loop.item.x}}` → `item`);只有根就是空串。 */
function refField(ref: string): string {
  return ref.slice(2, -2).trim().split(".")[1] ?? "";
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
  /** 整张图(含所有循环体 / 子图)里的问题。画布上某一层怎么挂角标见 issuesAtLayer。 */
  issues: NodeIssue[];
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
 * 每条问题记的是**它真正所在的那一层和那个节点**(`path` + `nodeId`)。画布在哪一层,就由
 * issuesAtLayer 把问题折到那一层看得见的节点上:体里的问题在主流程上挂在容器头上,钻进去
 * 就挂在出问题的那个节点上。此前问题一律改记到外层容器名下,于是钻进循环体一个角标都看不到,
 * 点清单也只会被弹回主流程、停在容器上。
 */
function collect(
  graph: WorkflowGraph,
  registry: RegistryLike,
  ctx: AnalyzeContext,
  issues: NodeIssue[],
  scopeExtras: ReadonlySet<string> = new Set(),
  path: ScopePath = [],
  insideName = "",
): void {
  const nodeIds = new Set([...graph.nodes.map((n) => n.id), ...scopeExtras]);
  const reachable = reachableFromStart(graph);
  // 「没有开始节点」只对顶层成立 —— 循环体本来就没有 start,它由外层驱动。
  const hasStart = graph.nodes.some((n) => n.type === "start");
  if (!hasStart && path.length === 0) {
    issues.push({
      nodeId: "__workflow__",
      path,
      nodeName: "Workflow",
      nodeType: "workflow",
      severity: "error",
      code: "missing-start",
    });
  }
  // 开始节点有哪些参数:声明在它 params 里的那几个(`*params`,同它的输出声明)。编辑器里的运行不带参数
  // (runWorkflow 只给 id),所以没声明的运行时就是空串 —— 与后端 _unresolved_reference_errors 同一条。
  // 体里没有开始节点,体内引到外层的另由失效引用报。
  const startParams = new Map(
    graph.nodes
      .filter((n) => n.type === "start")
      .map((n) => [n.id, new Set(declaredFieldNames(["*params"], n.config as Record<string, unknown> | undefined))]),
  );
  const startParamMissing = (sourceId: string, field: string) => {
    const params = startParams.get(sourceId);
    return Boolean(params && field && !params.has(field));
  };
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
        nodeId: node.id,
        path,
        nodeName: insideName ? `${insideName} › ${nodeName}` : nodeName,
        nodeType: node.type,
        severity,
        code,
        ...extra,
      });
    // 节点类型不在目录里(目录由后端按已装、已启用的插件给)。后端跑到它直接报「未知的节点类型」——
    // 先在清单里说,别等前面几步跑完、花了钱才知道;画布上它也只剩一个裸的 `plugin.包.工具`。
    if (!meta) push("error", "unknown-type");

    // 容器节点自己的 output / condition 在**体内**作用域里解析:看得见的是体里的节点和声明的作用域名。
    const bodyField = bodyKey(registry, node.type);
    const innerGraph = bodyField ? config[bodyField] : undefined;
    const innerNames = new Set([
      ...(innerGraph && typeof innerGraph === "object" && Array.isArray((innerGraph as WorkflowGraph).nodes)
        ? (innerGraph as WorkflowGraph).nodes.map((inner) => inner.id)
        : []),
      ...bodyScope(registry, node.type),
    ]);

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
      // 子图/循环体的 body/output/condition 引用子作用域或内部节点,不拿这一层的节点表判(否则误报)。
      // 但 output / condition 也不是不判:按体内节点 + 声明的作用域名判(与后端 validate_body_graph 的
      // container 同一条)。此前直接跳过,条件循环的条件写错一个节点名,运行时是空串,循环只跑一轮。
      if (isNestedScopeConfig(registry, node.type, key)) {
        if (key === bodyField) continue;
        for (const { ref, sourceId } of extractRefs(config[key])) {
          if (!innerNames.has(sourceId)) push("error", "stale-var", { configKey: key, ref });
        }
        continue;
      }
      // 代码字段里的 {{…}} 不是引用:不查失效,只提醒一句它不会被替换(上游的值请接到 input)。
      // 接了数据边就不只是提醒:上游的值整段当成代码跑,后端运行前拒(wfErr_codeFieldBound),这里同一条。
      if (spec.type === "code") {
        if (dataBound.has(`${node.id}:${key}`)) push("error", "code-field-bound", { configKey: key });
        if (extractRefs(config[key]).length > 0) push("warn", "code-template", { configKey: key });
        continue;
      }
      for (const { ref, sourceId } of extractRefs(config[key])) {
        // start 的 *params 通配前缀不算节点 id;引用不存在的节点即失效。
        if (!nodeIds.has(sourceId)) push("error", "stale-var", { configKey: key, ref });
        else if (startParamMissing(sourceId, refField(ref))) push("error", "start-param-missing", { configKey: key, ref });
      }
    }

    // 开始节点点名为必填的参数(required_params,逗号分隔)一个都不能空 —— 与后端 validate_graph 的
    // _start_param_errors 同一条规矩。参数被别处用 {{start.x}} 引用,引用本身在上面的必填检查里算"填了"。
    if (node.type === "start") {
      const params = (config.params ?? {}) as Record<string, unknown>;
      for (const name of String(config.required_params ?? "").replace(/，/g, ",").split(",")) {
        const key = name.trim();
        if (key && isEmpty(params[key])) push("error", "required-missing", { configKey: key });
      }
    }

    // 同组(one_of)恰好填一个 —— 与后端 validate_graph 的 _one_of_errors 同一条规矩。
    for (const group of oneOfGroups(fieldSpecs)) {
      const filled = group.filter((key) => !isEmpty(config[key]) || dataBound.has(`${node.id}:${key}`));
      if (filled.length > 1) push("error", "one-of-both", { configKey: filled[0], group });
      if (filled.length === 0) push("error", "one-of-missing", { configKey: group[0], group });
    }

    // 往里走一层。体里的节点和外面一样会缺必填、会引用不存在的东西 —— 只是此前没人看。
    // 体存在哪个字段由声明说(scope.bodyKey),和画布钻进去的是同一个字段,路径因此对得上。
    const key = bodyKey(registry, node.type);
    const body = key ? config[key] : undefined;
    if (body && typeof body === "object" && Array.isArray((body as WorkflowGraph).nodes)) {
      collect(
        body as WorkflowGraph,
        registry,
        ctx,
        issues,
        new Set(bodyScope(registry, node.type)),
        [...path, node.id],
        insideName ? `${insideName} › ${nodeName}` : nodeName,
      );
    }

    // 绑定校验(与属性面板 bindingNotice 同源)
    if (node.type === "llm") {
      if (ctx.chatProfilesLoaded && ctx.chatProfileIds.size === 0) push("warn", "no-providers");
      const pid = config.profile_id;
      if (typeof pid === "string" && pid && ctx.chatProfilesLoaded && !ctx.chatProfileIds.has(pid))
        push("error", "provider-missing", { configKey: "profile_id" });
    }
    if (node.type === "ai_generate") {
      const mode = ctx.generationPromptMode?.(config) ?? "required";
      if (mode === "required" && isEmpty(config.prompt) && !dataBound.has(`${node.id}:prompt`)) {
        push("error", "required-missing", { configKey: "prompt" });
      }
      if (drivesDigitalHuman(node.type, config) && isEmpty(config.consent) && !dataBound.has(`${node.id}:consent`)) {
        push("error", "required-missing", { configKey: "consent" });
      }
      const provider = config.provider;
      if (
        typeof provider === "string" &&
        provider &&
        ctx.generationModelsLoaded &&
        !ctx.generationVendors.has(provider)
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
    const targetName = insideName ? `${insideName} › ${target.name || target.type}` : target.name || target.type;
    // 从开始节点拉出的数据边:`source_output` 就是参数名,同上面 {{start.x}} 那一条。
    if (startParamMissing(source.id, edge.source_output)) {
      issues.push({
        nodeId: target.id,
        path,
        nodeName: targetName,
        nodeType: target.type,
        severity: "error",
        code: "start-param-missing",
        configKey: edge.target_input,
        ref: `{{${source.id}.${edge.source_output}}}`,
      });
    }
    const actual = outputType(registry, source.type, edge.source_output);
    const expected = inputType(registry, target.type, edge.target_input);
    if (!typesCompatible(actual, expected)) {
      issues.push({
        nodeId: target.id,
        path,
        nodeName: targetName,
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
  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warnCount = issues.length - errorCount;
  return { issues, errorCount, warnCount, runnable: errorCount === 0 };
}

/** `path` 是不是 `layer` 本身或它里面的某一层。 */
function isWithin(path: ScopePath, layer: ScopePath): boolean {
  return path.length >= layer.length && layer.every((id, index) => path[index] === id);
}

/**
 * 画布停在 `layer` 这一层时,每个看得见的节点身上挂哪些问题:这一层自己的节点挂自己的,
 * 更深处的问题挂在通往它的那个容器上(主流程上看得出「循环里有东西要修」,钻进去再看是哪一个)。
 * 别的分支、更外层的问题不在这一层显示 —— 它们在就绪清单里,点一下会带人过去。
 */
export function issuesAtLayer(issues: readonly NodeIssue[], layer: ScopePath): Map<string, NodeIssue[]> {
  const out = new Map<string, NodeIssue[]>();
  for (const issue of issues) {
    if (!isWithin(issue.path, layer)) continue;
    const at = issue.path.length === layer.length ? issue.nodeId : issue.path[layer.length];
    out.set(at, [...(out.get(at) ?? []), issue]);
  }
  return out;
}

/** 一串问题里最重的那一档(角标的颜色)。 */
export function worstSeverity(issues: readonly NodeIssue[]): IssueSeverity {
  return issues.some((issue) => issue.severity === "error") ? "error" : "warn";
}
