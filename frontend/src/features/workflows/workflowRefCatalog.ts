import type { WorkflowGraph } from "@/api/client";
import { refLabel, type RefCatalog, type RefLook } from "@/features/nodeForms/refCatalog";
import { bareRef } from "@/features/nodeForms/refDoc";
import { outputPortName } from "@/features/workflows/portNames";
import {
  declaredFieldNames,
  graphAtScope,
  scopeContainer,
  scopeVariables,
  type ScopePath,
  type ScopeRegistry,
} from "@/features/workflows/scope";

/**
 * 工作流里**一个引用指的是什么**:这一层图的节点、节点注册表的声明、容器给体播的作用域变量、上次运行交回的输出 →
 * 表单那一层的引用目录(见 nodeForms/refCatalog)。
 *
 * - 显示:`{{report.json.verdict}}` → 节点的名字(没起名的用 id;插件节点用插件报的名字)· 输出口的名字(portNames.outputPortName,和画布上
 *   那个口同一个名字)· 子路径;
 * - 指不到:根不是这一层的节点、也不是作用域名 → 没有这个节点;节点在,而输出不在它声明的输出里(通配按配置展开,
 *   开始节点的输出就是它的参数)→ 没有这个输出。节点类型不在注册表里(插件没装)的不判输出 —— 说不清它有什么;
 * - 字段:输出声明了结构写在哪一格(注册表的 output_schema_from,那一格是 JSON Schema)就按 schema 列;上次运行这个
 *   输出交回的是对象,就按交回的键列。只往对象里走、不进数组(数组要下标),最多三层。
 */

/** 只读节点类型的输出声明:有哪些、叫什么、结构写在哪一格、哪几格按配置展开成口。 */
interface Registry {
  get(type: string):
    | {
        label?: string;
        outputs?: readonly string[];
        output_labels?: Record<string, string>;
        output_schema_from?: Record<string, string>;
        port_maps?: Record<string, { input?: string; output?: string }>;
      }
    | undefined;
}

const MAX_DEPTH = 3;
const MAX_FIELDS = 60;

export function workflowRefCatalog({
  graph,
  registry,
  scopeVariables = [],
  runOutputs = {},
}: {
  graph: WorkflowGraph;
  registry: Registry;
  /** 容器给体播的作用域变量(`{{loop.item}}`、`{{input.topic}}`);主流程里为空。 */
  scopeVariables?: readonly string[];
  /** 上次运行每个节点交回的输出(节点 id → 输出名 → 值)。 */
  runOutputs?: Readonly<Record<string, Readonly<Record<string, unknown>> | undefined>>;
}): RefCatalog {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  //: 作用域名 → 它底下的字段(已经按容器的配置展开过)。
  const scopes = new Map<string, Set<string>>();
  for (const ref of scopeVariables) {
    const [root, field = ""] = bareRef(ref).split(".");
    scopes.set(root, (scopes.get(root) ?? new Set()).add(field));
  }

  const look = (path: string): RefLook => {
    const [root, output, ...rest] = path.split(".");
    const node = nodes.get(root);
    if (node) {
      const meta = registry.get(node.type);
      //: 没起名的节点用 id —— 只有插件节点例外:它的名字加的时候就不写死(跟着插件报的走,见 useWorkflowCanvasEdits.newNode),
      //: 没起名就叫插件此刻报的名字,不是一串 `plugin-dev-…-1`。内置节点加的时候都写了名字,没名字的(智能体建的)照旧用 id。
      const name = node.name?.trim() || (node.type.startsWith("plugin.") ? meta?.label?.trim() : "") || node.id;
      if (output === undefined) return { parts: [name], problem: null };
      const outputs = meta ? declaredFieldNames(meta.outputs ?? [], node.config as Record<string, unknown> | undefined) : null;
      return {
        parts: [name, outputPortName(registry, node, [output, ...rest].join("."))],
        problem: outputs && !outputs.includes(output) ? { kind: "output", node: name, output } : null,
      };
    }
    const fields = scopes.get(root);
    if (fields) {
      return {
        parts: path.split("."),
        problem: output !== undefined && !fields.has(output) ? { kind: "output", node: root, output } : null,
      };
    }
    return { parts: path.split("."), problem: { kind: "node", node: root } };
  };

  const fields = (path: string): string[] => {
    const [root, output, ...rest] = path.split(".");
    const node = nodes.get(root);
    if (!node || !output || rest.length > 0) return [];
    const found: string[] = [];
    const schemaField = registry.get(node.type)?.output_schema_from?.[output];
    if (schemaField) schemaPaths((node.config ?? {})[schemaField], [], found);
    valuePaths(runOutputs[root]?.[output], [], found);
    return [...new Set(found)].slice(0, MAX_FIELDS);
  };

  return { look, fields };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** JSON Schema 里对象的每个属性(往对象属性里走,不进数组)。 */
function schemaPaths(schema: unknown, prefix: string[], out: string[]): void {
  if (!isPlainObject(schema) || prefix.length >= MAX_DEPTH) return;
  const properties = schema.properties;
  if (!isPlainObject(properties)) return;
  for (const [key, child] of Object.entries(properties)) {
    out.push([...prefix, key].join("."));
    schemaPaths(child, [...prefix, key], out);
  }
}

/** 一份交回的值里对象的每个键(往对象里走,不进数组)。 */
function valuePaths(value: unknown, prefix: string[], out: string[]): void {
  if (!isPlainObject(value) || prefix.length >= MAX_DEPTH) return;
  for (const [key, child] of Object.entries(value)) {
    out.push([...prefix, key].join("."));
    valuePaths(child, [...prefix, key], out);
  }
}

/**
 * **一句话里提到一个引用时怎么说它**:`{{start.topic}}` → 「填主题 · topic」。就绪检查的提示(画布角标、就绪清单)、
 * 画布上引用提示线的悬停说明都拼着引用,经这里换成名字 —— 界面上不摆 `{{…}}`。
 *
 * 引用按它所在的那一层解析(`path`:主流程是 `[]`,体里是从主流程往里经过的容器):那一层的节点,加上容器给体播的
 * 作用域变量。每一层的目录只建一次。引用写不写花括号都认(`{{a.b}}` / `a.b`)。
 */
export function workflowRefNamer(
  root: WorkflowGraph,
  registry: Registry & ScopeRegistry,
): (ref: string, path?: ScopePath) => string {
  const catalogs = new Map<string, RefCatalog>();
  return (ref, path = []) => {
    const key = JSON.stringify(path);
    let catalog = catalogs.get(key);
    if (!catalog) {
      catalog = workflowRefCatalog({
        graph: graphAtScope(root, path, registry) ?? { nodes: [], edges: [] },
        registry,
        scopeVariables: scopeVariables(scopeContainer(root, path, registry), registry),
      });
      catalogs.set(key, catalog);
    }
    return refLabel(catalog.look(bareRef(ref).trim()));
  };
}

/** 没有图可查时(或在图之外)怎么说一个引用:按路径分段 —— 照样不摆花括号。 */
export function plainRefName(ref: string): string {
  return bareRef(ref).trim().split(".").join(" · ");
}
