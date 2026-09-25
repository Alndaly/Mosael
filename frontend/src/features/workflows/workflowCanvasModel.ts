import type { Edge, Node } from "@xyflow/react";

import { canvasEdgeClass } from "@/components/app/canvasEdges";
import { toMarkerNodes } from "@/features/markers/markers";
import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import {
  inputType,
  outputLabel,
  outputType,
  typesCompatible,
  type NodeIssue,
} from "@/features/workflows/analyze";
import type { WorkflowNodeData } from "@/features/workflows/WorkflowNode";
import type { DataType } from "@/features/nodeForms/fieldTypes";

type NodeRegistry = Map<string, WorkflowNodeType>;
type Translate = (key: MessageKey) => string;

/** Keep React Flow's visual selection in lockstep with the node shown by the inspector. */
export function withSingleNodeSelected<T extends Node>(nodes: T[], nodeId: string | null): T[] {
  return nodes.map((node) => {
    const selected = node.id === nodeId;
    return node.selected === selected ? node : { ...node, selected };
  });
}

/** Return a concrete configured asset id; template references cannot be previewed before a run. */
export function configAssetId(
  node: WorkflowGraph["nodes"][number],
  registry: NodeRegistry,
): string {
  for (const [key, value] of Object.entries(node.config ?? {})) {
    if (inputType(registry, node.type, key) !== "asset") continue;
    const text = String(value ?? "").trim();
    if (text && !text.includes("{{")) return text;
  }
  return "";
}

/** The compact configuration clue shown on a node card. */
const SUMMARY_KEYS = ["model", "workflow_id", "voice", "seconds", "url", "tool_name"] as const;

export function workflowConfigSummary(node: WorkflowGraph["nodes"][number]): string {
  const config = node.config ?? {};
  for (const key of SUMMARY_KEYS) {
    const text = String(config[key] ?? "").trim();
    if (text && !text.includes("{{")) return text;
  }
  return "";
}

/**
 * 这块画布的层次 —— **一处说了算**。理由见 markers.toMarkerNodes 上那段说明。
 *
 * 950 是个大数,因为 React Flow 把连线画在它自己的一层上:节点要压到连线之上才需要跨过
 * 那一层。节点本身不设 zIndex(走默认),所以这张表只有一行 —— 但它是那条"旗子在最上面"
 * 的规则**唯一**写下来的地方,而不是调用处一个看不出所以然的字面量。
 */
const LAYERS = { marker: 950 } as const;

export function toMarkerFlowNodes(graph: WorkflowGraph): Node[] {
  return toMarkerNodes(graph.markers ?? [], LAYERS.marker);
}

/** Domain graph → React Flow presentation. The domain graph remains the source of truth. */
export function toWorkflowFlowNodes(graph: WorkflowGraph, registry: NodeRegistry): Node[] {
  return [...toMarkerFlowNodes(graph), ...(graph.nodes ?? []).map((node) => ({
    id: node.id,
    type: "wf",
    position: node.position ?? { x: 80, y: 80 },
    data: {
      label: node.name || registry.get(node.type)?.label || node.type,
      nodeType: node.type,
      typeLabel: registry.get(node.type)?.label ?? node.type,
      inputs: node.inputs ?? [],
      // Wildcard outputs (for example start.*params) are references, not concrete handles.
      outputs: (registry.get(node.type)?.outputs ?? []).filter((output) => !output.startsWith("*")),
      configSummary: workflowConfigSummary(node),
    } satisfies WorkflowNodeData,
    deletable: true,
  }))];
}

/**
 * Resolve the presentation metadata for both sides of a node without changing its stable port keys.
 *
 * This stays outside the React component because the registry arrives asynchronously: the initial
 * graph projection may run before node metadata has loaded, while every later render can call this
 * pure function with the current registry.
 */
export function workflowPortPresentation(
  node: Pick<WorkflowNodeData, "nodeType" | "inputs" | "outputs">,
  registry: NodeRegistry,
): Pick<WorkflowNodeData, "inputTypes" | "inputLabels" | "outputTypes" | "outputLabels"> {
  const meta = registry.get(node.nodeType);
  const inputs = node.inputs ?? [];
  const outputs = node.outputs ?? [];
  return {
    inputTypes: Object.fromEntries(inputs.map((key) => [key, inputType(registry, node.nodeType, key)])),
    inputLabels: Object.fromEntries(
      inputs.map((key) => {
        const spec = meta?.config?.[key] as { label?: unknown } | undefined;
        return [key, String(spec?.label ?? "").trim()];
      }),
    ),
    outputTypes: Object.fromEntries(outputs.map((key) => [key, outputType(registry, node.nodeType, key)])),
    //: 取名字只有一处(analyze.outputLabel)—— 接点、产出面板、节点卡片读的是同一句声明。
    outputLabels: Object.fromEntries(outputs.map((key) => [key, outputLabel(registry, node.nodeType, key)])),
  };
}

/** Domain edges → React Flow handles, labels and soft type-mismatch styling. */
export function toWorkflowFlowEdges(
  graph: WorkflowGraph,
  t: Translate,
  registry: NodeRegistry,
): Edge[] {
  const nodeType = new Map((graph.nodes ?? []).map((node) => [node.id, node.type]));
  return (graph.edges ?? []).map((edge) => {
    if (edge.kind === "data") {
      const mismatch =
        edge.source_output &&
        edge.target_input &&
        !typesCompatible(
          outputType(registry, nodeType.get(edge.source) ?? "", edge.source_output),
          inputType(registry, nodeType.get(edge.target) ?? "", edge.target_input),
        );
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.source_output ? `out:${edge.source_output}` : undefined,
        targetHandle: edge.target_input ? `in:${edge.target_input}` : undefined,
        //: 样子见 components/app/canvasEdges 那张表:流动虚线,颜色在「数据」和「类型不匹配」里二选一。
        className: canvasEdgeClass(mismatch ? "mismatch" : "data", { flow: true }),
        //: 数据线不画箭头(方向由流动的虚线说)。写成 undefined 是为了**盖掉** defaultEdgeOptions 的默认箭头。
        markerEnd: undefined,
        data: { kind: "data" },
      };
    }
    const branch = edge.source_handle === "true" || edge.source_handle === "false" ? edge.source_handle : null;
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.source_handle ?? undefined,
      label:
        edge.source_handle === "true"
          ? t("wfEdgeTrue")
          : edge.source_handle === "false"
            ? t("wfEdgeFalse")
            : undefined,
      //: 箭头不在这里给:所有控制线用 defaultEdgeOptions 那一个,它取线自己的颜色(context-stroke),
      //: 真绿假红自然跟上。
      className: canvasEdgeClass(branch ?? "reference"),
    };
  });
}

function workflowDataTypeName(t: Translate, type: DataType | undefined): string {
  return t(`wfType_${type ?? "any"}` as MessageKey);
}

/** Structured readiness issue → localized text for badges and the checklist. */
export function workflowIssueText(t: Translate, issue: NodeIssue, registry: NodeRegistry): string {
  switch (issue.code) {
    case "missing-start":
      return t("wfIssueMissingStart");
    case "required-missing":
      return t("wfIssueRequired").replace("{k}", (() => {
        if (issue.nodeType === "ai_generate" && issue.configKey === "model") return t("wfGenModel");
        if (!issue.configKey) return "";
        const spec = registry.get(issue.nodeType)?.config?.[issue.configKey] as { label?: unknown } | undefined;
        return String(spec?.label ?? "").trim() || issue.configKey;
      })());
    case "stale-var":
      return t("wfIssueStaleVar").replace("{ref}", issue.ref ?? "");
    case "disconnected":
      return t("wfIssueDisconnected");
    case "no-providers":
      return t("wfIssueNoProviders");
    case "provider-missing":
      return t("wfIssueProviderMissing");
    case "gen-provider-unconfigured":
      return t("wfIssueGenUnconfigured");
    case "type-mismatch":
      return t("wfIssueTypeMismatch")
        .replace("{expected}", workflowDataTypeName(t, issue.expected))
        .replace("{actual}", workflowDataTypeName(t, issue.actual));
    default:
      return issue.code;
  }
}
