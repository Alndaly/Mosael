import type { WorkflowGraph } from "@/api/client";
import { layerReferences, type RegistryLike } from "@/features/workflows/analyze";
import { declaredFieldNames } from "@/features/workflows/scope";

/**
 * **一张卡片上画哪些数据接点** —— 卡片(workflowCanvasModel)和引用提示线找口(referenceHints)读的是这一份。
 *
 * - 输入口:接了上游的那几格(连接态 `inputs`),加上每条指进来的数据边的 `target_input`;
 * - 输出口:声明的输出(通配按配置展开 —— 开始节点的 `*params` 是它的每个参数),加上每条拉出去的数据边的 `source_output`。
 *   条件节点例外:它的出口是标题层的真 / 假两路,声明的 `result` 不另画口(卡片保持紧凑),只有真有数据边从它拉出时才画。
 *
 * 数据边两头一律画:连接态没记上这一格的旧图、插件没装(注册表里没有它的输出)、开始节点删掉了那个参数 —— 口不在,
 * React Flow 就不画这根线(只在控制台报 008),人看不见它,也就删不掉、改不了。画出来,就绪检查再说它哪里不对。
 */

type WNode = WorkflowGraph["nodes"][number];
type WEdge = WorkflowGraph["edges"][number];
type PortMap = { input?: string; output?: string };
type PortMeta = NonNullable<ReturnType<RegistryLike["get"]>> & {
  outputs?: readonly string[];
  port_maps?: Record<string, PortMap>;
};
type Registry = { get(type: string): PortMeta | undefined };

function mappedPorts(node: WNode, registry: Registry): { inputs: string[]; outputs: string[]; outputRoots: Set<string> } {
  const maps = registry.get(node.type)?.port_maps ?? {};
  const inputs: string[] = [];
  const outputs: string[] = [];
  const outputRoots = new Set<string>();
  for (const [configKey, map] of Object.entries(maps)) {
    const value = node.config?.[configKey];
    if (!value || typeof value !== "object" || Array.isArray(value)) continue;
    const keys = Object.keys(value);
    if (map.input) inputs.push(...keys.map((key) => `${map.input}.${key}`));
    if (map.output) {
      outputs.push(...keys.map((key) => `${map.output}.${key}`));
      outputRoots.add(map.output);
    }
  }
  return { inputs, outputs, outputRoots };
}

export function nodePorts(node: WNode, registry: Registry, edges: readonly WEdge[]): { inputs: string[]; outputs: string[] } {
  const wiredIn = edges.filter((edge) => edge.kind === "data" && edge.target === node.id && edge.target_input).map((edge) => edge.target_input!);
  const wiredOut = edges.filter((edge) => edge.kind === "data" && edge.source === node.id && edge.source_output).map((edge) => edge.source_output!);
  const mapped = mappedPorts(node, registry);
  const declared =
    node.type === "condition" ? [] : declaredFieldNames(registry.get(node.type)?.outputs ?? [], node.config as Record<string, unknown> | undefined);
  const referencedInputs = layerReferences(node, registry).map(({ targetInput }) => targetInput).filter(Boolean);
  return {
    inputs: [...new Set([...mapped.inputs, ...referencedInputs, ...(node.inputs ?? []), ...wiredIn])],
    // 动态属性已经把容器拆成逐项端口时，不再同时摆一个笼统的容器端口。
    outputs: [...new Set([...declared.filter((name) => !mapped.outputRoots.has(name)), ...mapped.outputs, ...wiredOut])],
  };
}
