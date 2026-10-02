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
import type { ScopePath } from "@/features/workflows/scope";
import { plainRefName } from "@/features/workflows/workflowRefCatalog";
import { nodePorts } from "@/features/workflows/workflowPorts";
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
      //: 画哪些口只有一处说了算(workflowPorts):开始节点每个参数一个口,每条数据边两头的口都在。
      ...nodePorts(node, registry, graph.edges ?? []),
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

/** 一组字段在界面上的名字(「素材 / 本机路径」),没有标签的退到键名。 */
function fieldLabels(issue: NodeIssue, registry: NodeRegistry): string {
  const specs = registry.get(issue.nodeType)?.config as Record<string, { label?: unknown } | undefined> | undefined;
  return (issue.group ?? [])
    .map((key) => String(specs?.[key]?.label ?? "").trim() || key)
    .join(" / ");
}

/** Structured readiness issue → localized text for badges and the checklist. */
/** 节点类型不在目录里时怎么说。插件节点说清是插件的事(没装、停用、工具没了),别的就是认不出的类型。 */
/**
 * 节点类型不在目录里时说什么。插件节点有后端给的真实原因(`reasons`,见 useUnusableNodeReasons)就说它 ——
 * 没装、没接、连接停用、工具没勾选,该去的地方各不相同;还没问到才退回那句笼统的话。
 */
export function unknownNodeTypeText(t: Translate, nodeType: string, reasons?: ReadonlyMap<string, string>): string {
  const reason = reasons?.get(nodeType);
  if (reason) return t("wfIssuePluginUnusable").replace("{reason}", reason);
  return t(nodeType.startsWith("plugin.") ? "wfIssuePluginUnavailable" : "wfIssueUnknownType").replace("{type}", nodeType);
}

export function workflowIssueText(
  t: Translate,
  issue: NodeIssue,
  registry: NodeRegistry,
  reasons?: ReadonlyMap<string, string>,
  /** 提示里提到的引用怎么说(见 workflowRefNamer):「节点标题 · 输出」。不给就按路径分段 —— 都不摆 `{{…}}`。 */
  refName: (ref: string, path: ScopePath) => string = plainRefName,
): string {
  const name = (ref: string | undefined) => (ref ? refName(ref, issue.path) : "");
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
    case "one-of-both":
      return t("wfIssueOneOfBoth").replace("{k}", fieldLabels(issue, registry));
    case "one-of-missing":
      return t("wfIssueOneOfMissing").replace("{k}", fieldLabels(issue, registry));
    case "stale-var":
      return t("wfIssueStaleVar").replace("{ref}", name(issue.ref));
    case "start-param-missing":
      return t("wfIssueStartParamMissing").replace("{ref}", name(issue.ref));
    case "start-param-not-an-option":
      return t("wfIssueStartParamNotAnOption")
        .replace("{k}", issue.configKey ?? "")
        .replace("{available}", (issue.available ?? []).join(" / "));
    case "body-empty":
      return t("wfIssueBodyEmpty");
    case "output-in-body":
      return t("wfIssueOutputInBody");
    case "scope-field-missing":
      return t("wfIssueScopeFieldMissing")
        .replace("{ref}", name(issue.ref))
        .replace("{available}", (issue.available ?? []).map(name).join(" / "));
    case "disconnected":
      return t("wfIssueDisconnected");
    case "unwired-referenced":
      return t("wfIssueUnwiredReferenced")
        .replace("{names}", (issue.referencedBy ?? []).join(t("listSeparator")))
        .replace("{refs}", (issue.refs ?? []).map(name).join(t("listSeparator")));
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
    case "code-template":
      return t("wfIssueCodeTemplate");
    case "code-field-bound":
      return t("wfIssueCodeFieldBound");
    case "unknown-type":
      return unknownNodeTypeText(t, issue.nodeType, reasons);
    default:
      return issue.code;
  }
}
