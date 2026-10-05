import type { GenerationOption, WorkflowGraph } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { canTakeUpstream } from "@/features/nodeForms/fieldTypes";
import type { ConfigSpec } from "@/features/nodeForms/NodeConfigForm";
import { sourceLineName } from "@/features/workflows/sourceAssetLines";
import { generationParameterLabel } from "@/lib/generationParameterLabels";

/**
 * **一个接点在哪、叫什么 —— 只此一处。**
 *
 * 画布卡片上的接点、引用提示线、检查器的「输出变量」、字段里的引用标签、就绪检查的提示,说到一个口时读的都是这里。
 * 名字取自**表单用的那一份声明**,按界面语言:
 *
 * - 一整格:节点目录给这一格的名字(「提示词」);
 * - 一格里的一项 —— 键值映射的一行、生成参数的一项、输入素材的一行:字段声明的 `entry_labels` 说从哪取
 *   (生成参数 → 「画面比例」,和检查器那一格同一个函数;输入素材 → 那一行的角色「首帧」);没声明的映射,键就是
 *   用户起的名字(开始参数、具名输出、子流程的入参);列表里说不出名字的一项是「字段名 n」;
 * - 输出:节点目录的输出名(后端保证同一个节点上不撞名,见 node_catalog.distinct_labels);按配置展开的输出
 *   (开始节点的参数、具名输出的每一项)是那一项的键。
 *
 * 此前卡片上的名字是**路径的最后一段**:引用写在 `parameters.aspect_ratio` 里,口就叫 `aspect_ratio`;写在
 * `source_assets` 的第一行,口就叫 `0` —— 检查器里同一格叫「画面比例」「首帧」。
 */

type PortNode = Pick<WorkflowGraph["nodes"][number], "type" | "config">;
type PortMap = { input?: string; output?: string };

/** 读名字要的那几样节点声明(节点目录 `WorkflowNodeType` 满足它)。 */
export interface PortRegistry {
  get(type: string):
    | {
        config?: Record<string, unknown>;
        output_labels?: Record<string, string>;
        port_maps?: Record<string, PortMap>;
      }
    | undefined;
}

// ── 在哪 ──────────────────────────────────────────────────────────────────────

/**
 * 一格配置**按什么单位接线** —— 接点是表单上能单独填的那一格:
 *
 * - `single`:整格一个口。一段字、一个数,也包括原始 JSON 框和代码:表单只给一个框,引用写在里面哪一层都是这一格;
 * - `entries`:对象的每个键一个口(键值映射的每一行、生成参数的每一项、插件结构化对象的每一格);
 * - `items`:列表的每一项一个口(输入素材的每一行);一项是一块结构的(插件 `editor: "items"`),每项的每一格一个口。
 */
export type FieldShape = "single" | "entries" | "items";

export function fieldShape(spec: ConfigSpec | undefined): FieldShape {
  if (!spec || spec.editor === "json" || spec.type === "code" || spec.type === "graph") return "single";
  if (spec.type === "object") return "entries";
  if (spec.type === "list" || spec.type === "asset_list" || spec.lines) return "items";
  return "single";
}

function configSpec(registry: PortRegistry, nodeType: string, field: string): ConfigSpec | undefined {
  return registry.get(nodeType)?.config?.[field] as ConfigSpec | undefined;
}

/**
 * 写在配置 `path`(`["parameters", "aspect_ratio"]`)上的一处引用,落在哪个输入口。
 *
 * 往下只走到表单能单独填的那一层(fieldShape):`llm` 的 JSON Schema 里三处描述都引用了开始参数时,口是
 * `json_schema` 一个 —— 此前是三个都叫 `description` 的口。
 */
export function inputPortPath(registry: PortRegistry, nodeType: string, path: readonly string[]): string {
  const spec = configSpec(registry, nodeType, path[0] ?? "");
  const shape = fieldShape(spec);
  const depth = shape === "single" ? 1 : shape === "items" && spec?.fields ? 3 : 2;
  return path.slice(0, depth).join(".");
}

/**
 * 这个输入口能不能接一条数据边 —— 和检查器的「接上游」同一个判据:一整格要它自己收得下上游的值(canTakeUpstream);
 * 一格里的一项(键值映射的一行、输入素材的一行)各自收得下。
 *
 * 原始 JSON 框这种整格一个口的,口在那里是为了让引用提示线有处可接;往上面拖一条数据边会把整份 JSON 换成上游的值。
 */
export function acceptsDataEdge(registry: PortRegistry, nodeType: string, key: string): boolean {
  const [field, ...rest] = key.split(".");
  const spec = configSpec(registry, nodeType, field);
  if (!spec) return true;
  return rest.length > 0 ? fieldShape(spec) !== "single" : canTakeUpstream(spec);
}

// ── 叫什么 ────────────────────────────────────────────────────────────────────

/**
 * 输出在节点目录里的名字(后端 `output_labels`,按界面语言)。没声明就是空串。
 *
 * 前端不编第二套名字:同一个输出在接点上叫「人声」、在产出里叫 `vocals_asset_id`,是同一件东西说两种话。
 */
function outputLabel(registry: PortRegistry, nodeType: string, output: string): string {
  return String(registry.get(nodeType)?.output_labels?.[output] ?? "").trim();
}

/**
 * 一个输出口(或引用里节点后面那一段,`json.verdict`)叫什么。
 *
 * 目录里有名字的用它;按配置逐项展开的(`port_maps`:「输出」节点的每一项具名输出)是那一项的键;开始节点的参数
 * 本来就是用户起的名字;底下的子路径(JSON 里的字段)原样跟在后面。和后端 node_types.reference_label 同一个取法。
 */
export function outputPortName(registry: PortRegistry, node: PortNode, key: string): string {
  const declared = outputLabel(registry, node.type, key);
  if (declared) return declared;
  const [root, ...rest] = key.split(".");
  const mapped = Object.values(registry.get(node.type)?.port_maps ?? {}).some((map) => map.output === root);
  if (mapped && rest.length > 0) return rest.join(" · ");
  return [outputLabel(registry, node.type, root) || root, ...rest].join(" · ");
}

export interface PortNameContext {
  registry: PortRegistry;
  /** 界面语言的文案表。 */
  t: (key: MessageKey) => string;
  /** 生成节点选的那个模型 —— 它自己声明的参数(插件生成供应商)用它声明的名字。清单还没到时不给。 */
  generationModel?: (config: Record<string, unknown>) => GenerationOption | null;
}

/**
 * 字段声明的 `entry_labels` → 一项叫什么。**和表单同一处取**:生成参数问 generationParameterLabel(检查器那一格的
 * 标题),输入素材问那一行的角色(sourceLineName,检查器按角色一行一格的标题)。说不出名字回空串。
 *
 * 后端声明了这里没有的来源时,接点名的棘轮(portsHaveHumanNames)会红 —— 名字不会悄悄退回键名。
 */
export const ENTRY_NAMES: Record<string, (context: PortNameContext, node: PortNode, field: string, entry: string) => string> = {
  generation_parameters: ({ t, generationModel }, node, _field, entry) =>
    generationParameterLabel(entry, generationModel?.(node.config ?? {}) ?? null, t),
  source_roles: ({ t }, node, field, entry) => sourceLineName(t, node.config?.[field], Number(entry)),
};

/** 结构里的一格(插件 `fields`)叫什么:它声明的名字,没有就是键。 */
function subFieldName(spec: ConfigSpec | undefined, name: string): string {
  return spec?.fields?.[name]?.label?.trim() || name;
}

/** 一个输入口(`prompt`、`parameters.aspect_ratio`、`source_assets.0`)叫什么。 */
export function inputPortName(context: PortNameContext, node: PortNode, key: string): string {
  const [field, entry, ...deeper] = key.split(".");
  const spec = configSpec(context.registry, node.type, field);
  const fieldName = spec?.label?.trim() || field;
  if (entry === undefined) return fieldName;
  const source = spec?.entry_labels ?? "";
  const named = Object.hasOwn(ENTRY_NAMES, source) ? ENTRY_NAMES[source](context, node, field, entry) : "";
  const shape = fieldShape(spec);
  if (shape === "items" && /^\d+$/.test(entry)) {
    const [sub, ...below] = deeper;
    const item = named || `${fieldName} ${Number(entry) + 1}`;
    return [item, ...(sub === undefined ? [] : [subFieldName(spec, sub), ...below])].join(" · ");
  }
  if (shape === "entries") return [named || subFieldName(spec, entry), ...deeper].join(" · ");
  return [fieldName, entry, ...deeper].join(" · ");
}

/** 同一份上下文给两侧取名:卡片的接点按它画。 */
export interface PortNamer {
  input(node: PortNode, key: string): string;
  output(node: PortNode, key: string): string;
}

export function workflowPortNamer(context: PortNameContext): PortNamer {
  return {
    input: (node, key) => inputPortName(context, node, key),
    output: (node, key) => outputPortName(context.registry, node, key),
  };
}
