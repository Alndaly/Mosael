import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { RefCatalog, RefLook } from "@/features/nodeForms/refCatalog";
import { bareRef } from "@/features/nodeForms/refDoc";
import { declaredFieldNames } from "@/features/workflows/scope";

/**
 * 工作流里**一个引用指的是什么**:这一层图的节点、节点注册表的声明、容器给体播的作用域变量、上次运行交回的输出 →
 * 表单那一层的引用目录(见 nodeForms/refCatalog)。
 *
 * - 显示:`{{report.json.verdict}}` → 节点的名字(没起名的用 id)· 输出的显示名(注册表的 output_labels)· 子路径;
 * - 指不到:根不是这一层的节点、也不是作用域名 → 没有这个节点;节点在,而输出不在它声明的输出里(通配按配置展开,
 *   开始节点的输出就是它的参数)→ 没有这个输出。节点类型不在注册表里(插件没装)的不判输出 —— 说不清它有什么;
 * - 字段:输出声明了结构写在哪一格(注册表的 output_schema_from,那一格是 JSON Schema)就按 schema 列;上次运行这个
 *   输出交回的是对象,就按交回的键列。只往对象里走、不进数组(数组要下标),最多三层。
 */

type Registry = ReadonlyMap<string, Pick<WorkflowNodeType, "outputs" | "output_labels" | "output_schema_from">>;

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
      const name = node.name?.trim() || node.id;
      if (output === undefined) return { parts: [name], problem: null };
      const outputs = meta ? declaredFieldNames(meta.outputs, node.config as Record<string, unknown> | undefined) : null;
      const label = meta?.output_labels?.[output]?.trim() || output;
      return {
        parts: [name, label, ...rest],
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
