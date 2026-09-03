import type { Edge, Node } from "@xyflow/react";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import {
  inputType,
  outputType,
  typesCompatible,
  type DataType,
  type NodeIssue,
} from "@/features/workflows/analyze";
import type { WorkflowNodeData } from "@/features/workflows/WorkflowNode";

type NodeRegistry = Map<string, WorkflowNodeType>;
type Translate = (key: MessageKey) => string;

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
const SUMMARY_KEYS = ["model", "workflow_id", "voice_id", "seconds", "url", "tool_name"] as const;

export function workflowConfigSummary(node: WorkflowGraph["nodes"][number]): string {
  const config = node.config ?? {};
  for (const key of SUMMARY_KEYS) {
    const text = String(config[key] ?? "").trim();
    if (text && !text.includes("{{")) return text;
  }
  return "";
}

/** Domain graph → React Flow presentation. The domain graph remains the source of truth. */
export function toWorkflowFlowNodes(graph: WorkflowGraph, registry: NodeRegistry): Node[] {
  return (graph.nodes ?? []).map((node) => ({
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
  }));
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
        className: mismatch ? "wf-edge-data wf-edge-mismatch" : "wf-edge-data",
        animated: true,
        markerEnd: undefined,
        data: { kind: "data" },
      };
    }
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
      className: edge.source_handle ? `wf-edge-${edge.source_handle}` : undefined,
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
