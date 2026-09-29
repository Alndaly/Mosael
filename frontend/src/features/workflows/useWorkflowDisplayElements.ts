import React from "react";
import type { Edge, Node } from "@xyflow/react";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { useI18n } from "@/app/preferences";
import { shapeEdges, type EdgeShape } from "@/components/app/canvasEdgeShape";
import { canvasEdgeClass } from "@/components/app/canvasEdges";
import { searchHighlightClass, type CanvasSearchHighlight } from "@/components/app/CanvasNodeSearch";
import type { CanvasMarker } from "@/features/markers/markers";
import { worstSeverity } from "@/features/workflows/analyze";
import { outputSummary } from "@/features/workflows/RunOutputs";
import { assetOutputs, outputRows } from "@/features/workflows/runSteps";
import type { WorkflowRunState } from "@/features/workflows/useWorkflowRun";
import type { WorkflowNodeData } from "@/features/workflows/WorkflowNode";
import { configAssetId, workflowIssueText, workflowPortPresentation } from "@/features/workflows/workflowCanvasModel";
import { isMarkerNode } from "@/features/workflows/workflowViewShared";
import { cn } from "@/lib/utils";

//: 交给 React Flow 画的那一份节点和边:在画布状态(nodes / edges)上叠运行状态、角标、层级、查找高亮。
//: 只是派生,不改画布状态本身(改了会打断拖拽)。

/** 边:按所选线形走,运行走过的那几条换成「走过」的样子。 */
export function useWorkflowDisplayEdges(
  edges: Edge[],
  runByNode: WorkflowRunState["runByNode"],
  edgeShape: EdgeShape,
): Edge[] {
  return React.useMemo(() => {
    // type 显式写到每条边上,而不是只靠 defaultEdgeOptions —— 后者的语义是"新建边的默认值",
    // 指望它去改已存在的边是碰运气。
    const shaped = shapeEdges(edges, edgeShape);
    if (Object.keys(runByNode).length === 0) return shaped;
    return shaped.map((edge) => {
      const from = runByNode[edge.source];
      const to = runByNode[edge.target];
      const taken = from && to && from.status !== "skipped" && to.status !== "skipped";
      //: 走过的线换成「运行走过」那一种(见 components/app/canvasEdges 的表)。颜色类是互斥的,
      //: 所以整串重给,而不是在原来的类后面再追加一个去和它比权重;数据线留着流动的虚线。
      //: 不写行内 style —— 此前写死的 success + 2.4px 压过了一切,选中它也不变主色。
      return taken ? { ...edge, className: canvasEdgeClass("taken", { flow: edge.data?.kind === "data" }) } : edge;
    });
  }, [edges, runByNode, edgeShape]);
}

/** 节点:角标、运行状态与产出、手动层级、查找高亮;标记另走一套。 */
export function useWorkflowDisplayNodes({
  nodes,
  graph,
  registry,
  t,
  layerIssues,
  runByNode,
  nodeZ,
  markers,
  patchMarker,
  deleteMarker,
  markerMode,
  markersVisible,
  annotationMode,
  searchHit,
  atRoot,
}: {
  nodes: Node[];
  graph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  t: ReturnType<typeof useI18n>;
  layerIssues: WorkflowRunState["layerIssues"];
  runByNode: WorkflowRunState["runByNode"];
  nodeZ: Record<string, number>;
  markers: CanvasMarker[];
  patchMarker: (next: CanvasMarker) => void;
  deleteMarker: (id: string) => void;
  markerMode: boolean;
  markersVisible: boolean;
  annotationMode: boolean;
  searchHit: CanvasSearchHighlight | null;
  atRoot: boolean;
}) {
  return React.useMemo(
    () => {
      //: 画布节点(react-flow 的)身上没有 config,配置在图里。按 id 取回来。
      const graphNode = (id: string) =>
        graph.nodes.find((one) => one.id === id) ?? { id, type: "", config: {} };
      return nodes.map((node) => {
        // 标记不是工作流节点:它没有类型、没有接点、没有就绪度,下面那一整套算它就是白算。
        if (isMarkerNode(node)) {
          return { ...node, hidden: !markersVisible, focusable: markerMode, draggable: markerMode, selectable: markerMode, selected: markerMode && node.selected, style: { ...node.style, pointerEvents: markerMode ? "auto" as const : "none" as const }, data: { ...node.data, markers, editable: markerMode, onChange: patchMarker, onDelete: deleteMarker } };
        }
        // 角标按**这一层**折好了(layerIssues):这一层自己的节点挂自己的问题,更深处的挂在通往它的容器上。
        // 运行状态仍只认主流程:体里的节点不发事件(子图不带 job),体里的 id 又是另一套命名空间
        // (体里也可以有一个 llm-1),拿去查只会张冠李戴。
        const nodeIssues = layerIssues.get(node.id);
        const badge = nodeIssues
          ? { severity: worstSeverity(nodeIssues), count: nodeIssues.length, title: nodeIssues.map((i) => workflowIssueText(t, i, registry)).join("\n") }
          : null;
        const step = atRoot ? runByNode[node.id] : undefined;
        return {
          ...node,
          className: cn(node.className, searchHighlightClass(searchHit, node.id)) || undefined,
          draggable: !annotationMode, selectable: !annotationMode,
          zIndex: nodeZ[node.id],
          data: {
            ...node.data,
            badge,
            run: step ? { status: step.status, ms: step.ms, error: step.error, message: step.message } : null,
            runAssets: assetOutputs(outputRows(registry, node.data.nodeType as string, step?.outputs)),
            runSummary: outputSummary(registry, node.data.nodeType as string, step?.outputs),
            // **这两项算在这里,不在 toWorkflowFlowNodes。** 那个函数跑在 useState 的初始化里,
            // 那一刻节点类型还没拉回来、registry 是空的 —— 算出来的永远是空值,而且不会重算。
            // (素材节点的缩略图和图标就是这么丢的:改成读注册表之后,读的是一张还没到货的表。)
            configAssetId: configAssetId(graphNode(node.id), registry),
            ...workflowPortPresentation(node.data as WorkflowNodeData, registry),
          },
        };
      });
    },
    // registry / graph 也要在里面:缩略图和接点类型都读它们,漏了就一直是加载前的空值。
    [nodes, layerIssues, t, runByNode, nodeZ, registry, graph, markers, patchMarker, deleteMarker, markerMode, markersVisible, annotationMode, searchHit, atRoot],
  );
}
