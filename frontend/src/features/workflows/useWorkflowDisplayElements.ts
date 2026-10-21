import React from "react";
import type { Edge, Node } from "@xyflow/react";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { useI18n } from "@/app/preferences";
import { shapeEdges, laneEdges, type EdgeHeightRank, type EdgeShape } from "@/components/app/canvasEdgeShape";
import { canvasEdgeClass } from "@/components/app/canvasEdges";
import { searchHighlightClass, type CanvasSearchHighlight } from "@/components/app/CanvasNodeSearch";
import type { CanvasMarker } from "@/features/markers/markers";
import { worstSeverity } from "@/features/workflows/analyze";
import type { PortNamer } from "@/features/workflows/portNames";
import { outputSummary } from "@/features/workflows/RunOutputs";
import { assetOutputs, outputRows } from "@/features/workflows/runSteps";
import type { WorkflowRunState } from "@/features/workflows/useWorkflowRun";
import type { WorkflowNodeData } from "@/features/workflows/WorkflowNode";
import { configAssetId, workflowIssueText, workflowNodeSubtitle, workflowPortPresentation } from "@/features/workflows/workflowCanvasModel";
import { feishuTargetParents, useFeishuTargetNames } from "@/features/workflows/feishuTargets";
import type { ScopePath } from "@/features/workflows/scope";
import { useUnusableNodeReasons } from "@/features/workflows/useUnusableNodeReasons";
import { nodePorts } from "@/features/workflows/workflowPorts";
import { isMarkerNode } from "@/features/workflows/workflowViewShared";
import { useGenerationOptions } from "@/lib/generationOptions";
import { cn } from "@/lib/utils";

//: 生成选项按种类各取一份(和检查器同一份缓存)。
const GENERATION_KINDS = ["image", "video", "audio"] as const;

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
      //: 走过的线换成「运行走过」那一种(见 components/app/canvasEdges 的表):紫色、虚线和**唯一
      //: 那支动画**。颜色类是互斥的,所以整串重给,而不是在原来的类后面再追加一个去和它比权重。
      //: 数据线与否都一个样 —— 会走才看得出「这根跑过」,画布上也只有这一刻的线该动。
      //: 不写行内 style —— 此前写死的 success + 2.4px 压过了一切,选中它也不变主色。
      return taken ? { ...edge, className: canvasEdgeClass("taken") } : edge;
    });
  }, [edges, runByNode, edgeShape]);
}

/**
 * 一对节点里每条边**天生**排在多高 —— 错开时先按它排,再按 id 断平(见 canvasEdgeShape 的平行边)。
 *
 * 卡片上接点的先后是死的:控制口在标题层(进出各一个),数据口在页脚的接点行上,行越靠后越低;
 * 条件节点那两路(真 18 / 假 38)夹着控制口(28)。同一对节点共用两头,所以**两侧行号相加**和真实
 * 中段的高度同序 —— 页脚相对卡片顶端那个偏移是个常数,不影响排序(它只决定"控制口该算哪一行",
 * 而控制口一定在所有数据行之上,这里按 -1 算)。
 *
 * 只为了让道次别把线插到一起:**道次是从中间往外分的**,顺序错了,天然在上面那根会分到往下的道次,
 * 两根就互相穿过去(实测:控制线(中段 29)往下一道、页脚第一行的数据线(78)往上一道 —— 49 的天然
 * 间隔撞上 48 的跨度,差 0.8px,正好叠上)。
 */
export function canvasEdgeHeightRank(
  graph: WorkflowGraph,
  registry: Map<string, WorkflowNodeType>,
): (edge: Edge) => number {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const ports = new Map<string, { inputs: string[]; outputs: string[] }>();
  const portsOf = (id: string) => {
    const found = ports.get(id);
    if (found) return found;
    const node = nodes.get(id);
    const computed = node ? nodePorts(node, registry, graph.edges ?? []) : { inputs: [], outputs: [] };
    ports.set(id, computed);
    return computed;
  };
  /** 接点在卡片上的行号:控制口(没有 id 的那种)在标题层,记 -1;数据口是页脚第几行(从 2 起,页脚整个在标题层下面)。 */
  const rowOf = (handle: string | null | undefined, list: string[], branch: boolean) => {
    if (handle === null || handle === undefined) return -1;
    //: 条件节点那两路(真 18 / 假 38)夹着控制口(28)—— 它们的值就是 "true" / "false",不带 in:/out: 前缀。
    if (branch && (handle === "true" || handle === "false")) return handle === "true" ? -1.5 : 0.5;
    const index = list.indexOf(handle.replace(/^(in|out):/, ""));
    return 2 + (index >= 0 ? index : 0);
  };
  const isCondition = (id: string) => nodes.get(id)?.type === "condition";
  return (edge) =>
    rowOf(edge.sourceHandle, portsOf(edge.source).outputs, isCondition(edge.source)) +
    rowOf(edge.targetHandle, portsOf(edge.target).inputs, false);
}

/**
 * 交给 React Flow 的那一整串边:引用提示线排在前面(**先画**,后画的真连线压在它上面),真连线按
 * 标注模式关掉可选中,整体再按「同一对节点之间的第几条」错开(见 canvasEdgeShape 的平行边)。
 *
 * **错开必须在这一层、对两串一起算。** 规范化不再折掉「同一对节点间的控制边」之后,一对节点上会同时
 * 挂控制线(实线,说先后)和数据线(虚线,说哪个值流过去),外加画在这一对上的引用提示线 —— 分组要
 * 看的是「这一对节点上一共画了几根」,分开算的话两边都以为自己是独苗,照旧重合。
 *
 * **分组只看两头是谁,不看 id 前缀**(`d-` / `e-` / `ref-hint:` 各有各的来历,那不是边的性质):
 * 谁和谁在同一对节点上,图里就写着(source / target)。`heightOf` 见 canvasEdgeHeightRank。
 */
export function canvasEdgesForFlow(
  hintEdges: Edge[],
  displayEdges: Edge[],
  { annotationMode, heightOf }: { annotationMode: boolean; heightOf?: EdgeHeightRank },
): Edge[] {
  return laneEdges([...hintEdges, ...displayEdges.map((edge) => ({ ...edge, selectable: !annotationMode }))], heightOf);
}

/** 节点:角标、运行状态与产出、手动层级、查找高亮;标记另走一套。 */
export function useWorkflowDisplayNodes({
  nodes,
  graph,
  registry,
  workspaceId,
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
  refName,
  portNamer,
}: {
  nodes: Node[];
  graph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  /** 现查收件人目录要它(见 feishuTargets)。 */
  workspaceId: string;
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
  /** 角标说明里提到的引用怎么说:「节点标题 · 输出」(见 workflowRefNamer)。 */
  refName: (ref: string, path: ScopePath) => string;
  /** 卡片上的接点叫什么(见 portNames)。 */
  portNamer: PortNamer;
}) {
  //: 认不出的插件节点为什么用不了(后端说的真实原因),角标的提示里说它。
  const unknownTypes = React.useMemo(
    () => [...layerIssues.values()].flat().filter((issue) => issue.code === "unknown-type").map((issue) => issue.nodeType),
    [layerIssues],
  );
  const unusableReasons = useUnusableNodeReasons(unknownTypes);
  //: 卡片上那一行写选中的模型叫什么(两层名字的主名,见 workflowNodeSubtitle):和检查器、AI Studio 读同一份缓存
  const generationModels = useGenerationOptions(GENERATION_KINDS);
  //: 飞书那两个节点卡上的收件人写**名字**而不是 `ou_…`:那一格的目录在这里取(只有这一张图真的用得上
  //: 哪一档才去问,见 feishuTargetParents)。查不到的值照旧写 id,不编名字。
  const feishuParents = React.useMemo(() => feishuTargetParents(graph), [graph]);
  const feishuNames = useFeishuTargetNames(workspaceId, feishuParents);
  //: 逐节点缓存:输入没变动的节点原样复用上一帧的结果(连对象身份都不变),React Flow 才会跳过重渲染。
  //: 拖动每帧只动被拖那一颗的位置 —— 此前整段 map 每帧给**所有**节点造新对象/新 data,几十个节点
  //: 的卡片每帧全量重画,拖起来掉帧、看着晕(维护者实测)。签名逐项比身份,便宜;命中的节点
  //: 只有位置/选中态可能变,那时包一层新对象(也只有它被重画)。
  const nodeCacheRef = React.useRef(new Map<string, { sig: unknown[]; result: Node }>());
  return React.useMemo(
    () => {
      //: 画布节点(react-flow 的)身上没有 config,配置在图里。按 id 取回来。
      const graphNode = (id: string) =>
        graph.nodes.find((one) => one.id === id) ?? { id, type: "", config: {} };
      //: runByNode / nodeZ 只按**每节点的值**进签名(nodeZ 挂在 nodes 上,拖动每帧换新对象,
      //: 进了全局签名缓存就每帧全灭 —— 那正是缓存最该起作用的时候)。
      //: 签名**摊平**成一维逐项比身份:嵌套数组的话,外层元素比的是数组身份,每跑一次全灭。
      const globalSig = [layerIssues, unusableReasons, t, registry, graph, markers, patchMarker, deleteMarker, markerMode, markersVisible, annotationMode, searchHit, atRoot, refName, portNamer, generationModels.options, generationModels.loaded, feishuNames];
      const cache = nodeCacheRef.current;
      const nextCache = new Map<string, { sig: unknown[]; result: Node }>();
      const built = nodes.map((node) => {
        // 标记不是工作流节点:它没有类型、没有接点、没有就绪度,下面那一整套算它就是白算。
        if (isMarkerNode(node)) {
          const sig = [node.data, markers, markerMode, markersVisible, patchMarker, deleteMarker, ...globalSig];
          const hit = cache.get(node.id);
          if (hit && sig.every((one, i) => one === hit.sig[i])) {
            const { position, dragging, selected } = node;
            if (hit.result.position === position && hit.result.dragging === dragging && hit.result.selected === selected) {
              nextCache.set(node.id, hit);
              return hit.result;
            }
            const moved = { ...hit.result, position, dragging, selected };
            nextCache.set(node.id, { sig, result: moved });
            return moved;
          }
          const result = { ...node, hidden: !markersVisible, focusable: markerMode, draggable: markerMode, selectable: markerMode, selected: markerMode && node.selected, style: { ...node.style, pointerEvents: markerMode ? "auto" as const : "none" as const }, data: { ...node.data, markers, editable: markerMode, onChange: patchMarker, onDelete: deleteMarker } };
          nextCache.set(node.id, { sig, result });
          return result;
        }
        // 角标按**这一层**折好了(layerIssues):这一层自己的节点挂自己的问题,更深处的挂在通往它的容器上。
        // 运行状态仍只认主流程:体里的节点不发事件(子图不带 job),体里的 id 又是另一套命名空间
        // (体里也可以有一个 llm-1),拿去查只会张冠李戴。
        const nodeIssues = layerIssues.get(node.id);
        const step = atRoot ? runByNode[node.id] : undefined;
        const gNode = graphNode(node.id);
        const sig = [node.data, nodeIssues, step, nodeZ[node.id], gNode, ...globalSig];
        const hit = cache.get(node.id);
        if (hit && sig.every((one, i) => one === hit.sig[i])) {
          const { position, dragging, selected } = node;
          if (hit.result.position === position && hit.result.dragging === dragging && hit.result.selected === selected) {
            nextCache.set(node.id, hit);
            return hit.result;
          }
          const moved = { ...hit.result, position, dragging, selected };
          nextCache.set(node.id, { sig, result: moved });
          return moved;
        }
        const badge = nodeIssues
          ? { severity: worstSeverity(nodeIssues), count: nodeIssues.length, title: nodeIssues.map((i) => workflowIssueText(t, i, registry, unusableReasons, refName)).join("\n") }
          : null;
        const result = {
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
            configAssetId: configAssetId(gNode, registry),
            configSummary: workflowNodeSubtitle(gNode, registry, generationModels.options, t, generationModels.loaded, feishuNames),
            ...workflowPortPresentation(gNode, node.data as WorkflowNodeData, registry, portNamer),
          },
        };
        nextCache.set(node.id, { sig, result });
        return result;
      });
      nodeCacheRef.current = nextCache;
      return built;
    },
    // registry / graph 也要在里面:缩略图和接点类型都读它们,漏了就一直是加载前的空值。
    [nodes, layerIssues, unusableReasons, t, runByNode, nodeZ, registry, graph, markers, patchMarker, deleteMarker, markerMode, markersVisible, annotationMode, searchHit, atRoot, refName, portNamer, generationModels.options, generationModels.loaded, feishuNames],
  );
}
