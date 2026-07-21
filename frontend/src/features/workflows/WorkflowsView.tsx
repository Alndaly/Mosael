import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useStore } from "zustand";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlignLeft,
  AlertTriangle,
  AudioLines,
  Bell,
  BookOpen,
  Bot,
  Braces,
  CaseSensitive,
  CircleCheck,
  Code2,
  Download,
  Flag,
  GitBranch,
  Globe,
  History,
  Languages,
  Repeat,
  RefreshCw,
  Filter,
  ArrowLeft,
  Link2,
  Loader2,
  Mic,
  Pencil,
  Timer,
  PenLine,
  Play,
  Plus,
  Rocket,
  Redo2,
  Save,
  Search,
  Undo2,
  Sparkles,
  Trash2,
  X,
  Type,
  Wand2,
  Workflow as WorkflowIcon,
  Wrench,
  Tags,
  FolderInput,
  FolderPlus,
} from "lucide-react";
import { toast } from "sonner";

import {
  api,
  createWorkflow,
  deleteWorkflow,
  fetchWorkflowNodeTypes,
  listAssets,
  listCredentials,
  listPublishAccounts,
  listVoices,
  listWorkflows,
  runWorkflow,
  updateWorkflow,
  type Workflow,
  type WorkflowGraph,
  type WorkflowNodeType,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { ConfigNotice } from "@/components/layout/ConfigNotice";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { VarTextarea } from "@/features/workflows/VarTextarea";
import { CodeEditor, type CodeEditorHandle } from "@/components/ui/code-editor";
import { WorkflowAgentChat } from "@/features/workflows/WorkflowAgentChat";
import { WorkflowRunHistory } from "@/features/workflows/WorkflowRunHistory";
import { createWorkflowGraphStore } from "@/stores/workflowGraphStore";
import {
  analyzeWorkflow,
  extractRefs,
  inputType,
  outputType,
  typesCompatible,
  type DataType,
  type NodeIssue,
} from "@/features/workflows/analyze";

/** 节点类型 → 图标(与节点面板/画布一致)。 */
const NODE_ICONS: Record<string, React.ReactNode> = {
  start: <Flag size={13} />,
  llm: <Sparkles size={13} />,
  kb_search: <BookOpen size={13} />,
  plugin_tool: <Wrench size={13} />,
  transcribe_asset: <Mic size={13} />,
  export_sequence: <Download size={13} />,
  ai_generate: <Wand2 size={13} />,
  condition: <GitBranch size={13} />,
  http_request: <Globe size={13} />,
  code: <Code2 size={13} />,
  template: <AlignLeft size={13} />,
  publish: <Rocket size={13} />,
  json_extract: <Braces size={13} />,
  text_transform: <CaseSensitive size={13} />,
  delay: <Timer size={13} />,
  synthesize_speech: <AudioLines size={13} />,
  notify: <Bell size={13} />,
  translate: <Languages size={13} />,
  loop_foreach: <Repeat size={13} />,
  loop_while: <RefreshCw size={13} />,
  asset_query: <Filter size={13} />,
  asset_tag: <Tags size={13} />,
  asset_update: <FolderInput size={13} />,
  project_create: <FolderPlus size={13} />,
};

interface WfNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  typeLabel: string;
  /** 就绪度角标:分析出的最高严重度 + 问题条数 + 悬浮明细。 */
  badge?: { severity: "error" | "warn"; count: number; title: string } | null;
  /** 数据接点:左侧输入(连接态字段)、右侧输出(节点声明的 outputs)。 */
  inputs?: string[];
  outputs?: string[];
}

/** 画布节点:语义色图标 + 名称 + 类型标签,全平面卡片。
    条件节点右侧是「真/假」两个分支端点,其余节点单一出口。
    缺配置/失效引用/断连的节点在右上角挂一枚告警角标,一眼可辨。 */
function WfNode({ data, selected }: NodeProps) {
  const t = useI18n();
  const d = data as WfNodeData;
  const isCondition = d.nodeType === "condition";
  const badge = d.badge ?? null;
  const inputs = d.inputs ?? [];
  const outputs = d.outputs ?? [];
  // 条件节点保持紧凑(真/假分支端点),不上数据 IO 体;其余节点显示输入/输出接点。
  const showIo = !isCondition && (inputs.length > 0 || outputs.length > 0);
  return (
    <div
      className={`wf-node${showIo ? " has-io" : ""}${selected ? " selected" : ""}${
        badge ? ` has-issue is-${badge.severity}` : ""
      }`}
      data-node-type={d.nodeType}
    >
      {/* 控制入(左上) */}
      {d.nodeType !== "start" && (
        <Handle type="target" position={Position.Left} className="wf-handle wf-ctrl" style={{ top: 22 }} />
      )}
      <div className="wf-node-header">
        <span className={`wf-node-icon wf-icon-${d.nodeType}`}>{NODE_ICONS[d.nodeType] ?? <Type size={13} />}</span>
        <span className="wf-node-text">
          <strong>{d.label}</strong>
          {/* 未改名时 label 就是类型名,别再重复显示一行类型。 */}
          {d.label !== d.typeLabel && <small>{d.typeLabel}</small>}
        </span>
      </div>
      {badge && (
        <span className={`wf-node-badge is-${badge.severity}`} title={badge.title} aria-label={badge.title}>
          <AlertTriangle size={11} />
          {badge.count > 1 ? badge.count : null}
        </span>
      )}
      {isCondition ? (
        <>
          <Handle id="true" type="source" position={Position.Right} className="wf-handle wf-handle-true" style={{ top: "32%" }} />
          <Handle id="false" type="source" position={Position.Right} className="wf-handle wf-handle-false" style={{ top: "68%" }} />
          <span className="wf-branch-label true">真</span>
          <span className="wf-branch-label false">假</span>
        </>
      ) : (
        <Handle type="source" position={Position.Right} className="wf-handle wf-ctrl" style={{ top: 22 }} />
      )}
      {showIo && (
        <div className="wf-node-io">
          <div className="wf-io-col in">
            {inputs.map((key) => (
              <div className="wf-io-row" key={key}>
                <Handle
                  id={`in:${key}`}
                  type="target"
                  position={Position.Left}
                  className="wf-socket"
                  data-dtype={inputType(d.nodeType, key)}
                />
                <span className="wf-io-label">{FIELD_LABEL_KEYS[key] ? t(FIELD_LABEL_KEYS[key]) : key}</span>
              </div>
            ))}
          </div>
          <div className="wf-io-col out">
            {outputs.map((output) => (
              <div className="wf-io-row" key={output}>
                <span className="wf-io-label">{output}</span>
                <Handle
                  id={`out:${output}`}
                  type="source"
                  position={Position.Right}
                  className="wf-socket"
                  data-dtype={outputType(d.nodeType, output)}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const NODE_COMPONENT_TYPES = { wf: WfNode };

/** 配置字段 key → 人类可读标签键(Dify 式:面板不暴露裸 config key)。 */
const FIELD_LABEL_KEYS: Record<string, MessageKey> = {
  prompt: "wffPrompt",
  system: "wffSystem",
  profile_id: "wffProfile",
  model: "wffModel",
  query: "wffQuery",
  limit: "wffLimit",
  plugin_id: "wffPlugin",
  tool_name: "wffTool",
  input: "wffInput",
  asset_id: "wffAsset",
  dataset_id: "wffDataset",
  sequence_id: "wffSequence",
  provider: "wffProvider",
  kind: "wffKind",
  account_id: "wffAccount",
  title: "wffTitle",
  description: "wffDescription",
  left: "wffLeft",
  op: "wffOp",
  right: "wffRight",
  method: "wffMethod",
  url: "wffUrl",
  headers: "wffHeaders",
  body: "wffBody",
  code: "wffCode",
  template: "wffTemplate",
  params: "wffParams",
};

/** 连线统一带闭合箭头,方向一目了然。 */
const DEFAULT_EDGE_OPTIONS = {
  markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: "var(--border-strong)" },
};

export function WorkflowsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [menuRenaming, setMenuRenaming] = React.useState<Workflow | null>(null);
  const [menuDeleting, setMenuDeleting] = React.useState<Workflow | null>(null);

  // 通知/任务中心深链(mibu:open-* 事件通道):直接选中对应工作流。
  React.useEffect(() => {
    const onOpenWorkflow = (event: Event) => {
      const id = (event as CustomEvent<string>).detail;
      if (typeof id === "string" && id) setSelectedId(id);
    };
    window.addEventListener("mibu:open-workflow", onOpenWorkflow);
    return () => window.removeEventListener("mibu:open-workflow", onOpenWorkflow);
  }, []);

  const workflows = useQuery({
    queryKey: ["workflows", workspace.id],
    queryFn: () => listWorkflows(workspace.id),
    // 智能体经确认卡改图后 updated_at 变化,轮询让画布自动跟进。
    refetchInterval: 5000,
  });
  const nodeTypes = useQuery({ queryKey: ["workflow-node-types"], queryFn: fetchWorkflowNodeTypes, staleTime: Infinity });

  const create = useMutation({
    mutationFn: () => createWorkflow({ workspace_id: workspace.id, name: t("wfDefaultName"), description: "" }),
    onSuccess: (workflow) => {
      setSelectedId(workflow.id);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
  });

  const menuRename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => updateWorkflow(id, { name }),
    onSuccess: () => {
      setMenuRenaming(null);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
  });
  const menuRemove = useMutation({
    mutationFn: (id: string) => deleteWorkflow(id),
    onSuccess: () => {
      setMenuDeleting(null);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
  });
  const menuRun = useMutation({
    mutationFn: (id: string) => runWorkflow(id),
    onSuccess: (_data, id) => {
      toast.success(t("wfRunQueued"));
      // Without this the history panel, if already open with nothing in flight, never polls
      // and never refetches — the run appears only after navigating away and back.
      void qc.invalidateQueries({ queryKey: ["workflow-runs", id] });
    },
    onError: (error: Error) => toast.error(t("wfRunFailed"), { description: error.message }),
  });

  const selected = (workflows.data ?? []).find((w) => w.id === selectedId) ?? (workflows.data ?? [])[0] ?? null;

  if (workflows.isSuccess && (workflows.data ?? []).length === 0) {
    return (
      <div className="feature-view">
        <EmptyState
          icon={<WorkflowIcon size={22} />}
          title={t("wfEmptyTitle")}
          body={t("wfEmptyBody")}
          action={
            <Button disabled={create.isPending} onClick={() => create.mutate()}>
              <Plus size={15} /> {t("wfCreate")}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="feature-view">
      <div className="plugins-shell">
        <aside className="plugins-list panel">
          <div className="panel-head">
            <h2>{t("navWorkflows")}</h2>
            <Button variant="outline" size="sm" disabled={create.isPending} onClick={() => create.mutate()}>
              <Plus size={13} /> {t("wfCreate")}
            </Button>
          </div>
          <div className="plugins-list-body">
            {(workflows.data ?? []).map((workflow) => (
              <ContextMenu key={workflow.id}>
                <ContextMenuTrigger asChild>
                  <button
                    type="button"
                    className={selected?.id === workflow.id ? "plugins-item active" : "plugins-item"}
                    onClick={() => setSelectedId(workflow.id)}
                  >
                    <span className="plugins-item-text">
                      <strong>{workflow.name}</strong>
                      <small>
                        {t("wfNodeCount").replace("{n}", String((workflow.graph as unknown as WorkflowGraph).nodes?.length ?? 0))}
                      </small>
                    </span>
                  </button>
                </ContextMenuTrigger>
                <ContextMenuContent>
                  <ContextMenuItem onSelect={() => menuRun.mutate(workflow.id)}>
                    <Play /> {t("wfRun")}
                  </ContextMenuItem>
                  <ContextMenuItem onSelect={() => setMenuRenaming(workflow)}>
                    <Pencil /> {t("rename")}
                  </ContextMenuItem>
                  <ContextMenuSeparator />
                  <ContextMenuItem destructive onSelect={() => setMenuDeleting(workflow)}>
                    <Trash2 /> {t("delete")}
                  </ContextMenuItem>
                </ContextMenuContent>
              </ContextMenu>
            ))}
          </div>
        </aside>
        <div className="plugins-detail wf-detail">
          {selected && nodeTypes.data ? (
            <WorkflowEditor
              key={selected.id}
              workflow={selected}
              nodeTypes={nodeTypes.data}
              workspaceId={workspace.id}
            />
          ) : (
            <EmptyState icon={<WorkflowIcon size={22} />} title={t("pickDetailTitle")} body={t("pickDetailBody")} />
          )}
        </div>
      </div>
      <RenameDialog
        open={menuRenaming !== null}
        title={t("rename")}
        initialValue={menuRenaming?.name ?? ""}
        onCancel={() => setMenuRenaming(null)}
        onSubmit={(name) => menuRenaming && menuRename.mutate({ id: menuRenaming.id, name })}
      />
      <ConfirmDialog
        open={menuDeleting !== null}
        title={t("deleteConfirmTitle")}
        body={t("wfDeleteBody")}
        onCancel={() => setMenuDeleting(null)}
        onConfirm={() => menuDeleting && menuRemove.mutate(menuDeleting.id)}
      />
    </div>
  );
}

function toFlowNodes(graph: WorkflowGraph, registry: Map<string, WorkflowNodeType>): Node[] {
  return (graph.nodes ?? []).map((node) => ({
    id: node.id,
    type: "wf",
    position: node.position ?? { x: 80, y: 80 },
    data: {
      label: node.name || registry.get(node.type)?.label || node.type,
      nodeType: node.type,
      typeLabel: registry.get(node.type)?.label ?? node.type,
      inputs: node.inputs ?? [],
      // 过滤通配输出(如 start 的 *params),它们不是可连接的具体接点。
      outputs: (registry.get(node.type)?.outputs ?? []).filter((output) => !output.startsWith("*")),
    } satisfies WfNodeData,
    deletable: true,
  }));
}

function toFlowEdges(graph: WorkflowGraph): Edge[] {
  const nodeType = new Map((graph.nodes ?? []).map((node) => [node.id, node.type]));
  return (graph.edges ?? []).map((edge) => {
    // 数据边:接输出接点 out:x → 输入接点 in:y。蓝色流动虚线,不带箭头(终点是接点)。
    if (edge.kind === "data") {
      // 类型不匹配的数据边染成警示色(软提示,与就绪检查同源,不阻断)。
      const mismatch =
        edge.source_output &&
        edge.target_input &&
        !typesCompatible(
          outputType(nodeType.get(edge.source) ?? "", edge.source_output),
          inputType(nodeType.get(edge.target) ?? "", edge.target_input),
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
      label: edge.source_handle === "true" ? "真" : edge.source_handle === "false" ? "假" : undefined,
      className: edge.source_handle ? `wf-edge-${edge.source_handle}` : undefined,
    };
  });
}

/** issue code → 本地化文案(角标 tooltip / checklist 行都用它)。 */
function issueText(t: ReturnType<typeof useI18n>, issue: NodeIssue): string {
  switch (issue.code) {
    case "missing-start":
      return t("wfIssueMissingStart");
    case "required-missing":
      return t("wfIssueRequired").replace("{k}", issue.configKey ?? "");
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
        .replace("{expected}", typeName(t, issue.expected))
        .replace("{actual}", typeName(t, issue.actual));
    default:
      return issue.code;
  }
}

/** DataType → 本地化名。 */
function typeName(t: ReturnType<typeof useI18n>, type: DataType | undefined): string {
  const key = `wfType_${type ?? "any"}` as MessageKey;
  return t(key);
}

function WorkflowEditor({
  workflow,
  nodeTypes,
  workspaceId,
}: {
  workflow: Workflow;
  nodeTypes: WorkflowNodeType[];
  workspaceId: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const registry = React.useMemo(() => new Map(nodeTypes.map((item) => [item.type, item])), [nodeTypes]);

  // graph 是唯一事实(configs/names);放进 zustand+zundo store 拿撤销/重做,React Flow 只管几何与选中。
  // 每个 WorkflowEditor 一个 store(按 workflow.id 重挂),历史不跨工作流。
  const graphStoreRef = React.useRef<ReturnType<typeof createWorkflowGraphStore> | null>(null);
  if (graphStoreRef.current === null) {
    graphStoreRef.current = createWorkflowGraphStore(structuredClone(workflow.graph as unknown as WorkflowGraph));
  }
  const graphStore = graphStoreRef.current;
  const graph = useStore(graphStore, (s) => s.graph);
  const graphHasStart = graph.nodes.some((node) => node.type === "start");
  const setGraph = useStore(graphStore, (s) => s.setGraph);
  const canUndo = useStore(graphStore.temporal, (s) => s.pastStates.length > 0);
  const canRedo = useStore(graphStore.temporal, (s) => s.futureStates.length > 0);
  const [nodes, setNodes] = React.useState<Node[]>(() => toFlowNodes(workflow.graph as unknown as WorkflowGraph, registry));
  const [edges, setEdges] = React.useState<Edge[]>(() => toFlowEdges(workflow.graph as unknown as WorkflowGraph));
  const [dirty, setDirty] = React.useState(false);
  const [showHistory, setShowHistory] = React.useState(false);

  // 撤销/重做:temporal 改的是 store.graph,再从新 graph 重建 React Flow 的 nodes/edges。
  const syncFromGraph = React.useCallback(() => {
    const next = graphStore.getState().graph;
    setNodes(toFlowNodes(next, registry));
    setEdges(toFlowEdges(next));
    setDirty(true);
  }, [graphStore, registry]);
  const undo = React.useCallback(() => {
    if (graphStore.temporal.getState().pastStates.length === 0) return;
    graphStore.temporal.getState().undo();
    syncFromGraph();
  }, [graphStore, syncFromGraph]);
  const redo = React.useCallback(() => {
    if (graphStore.temporal.getState().futureStates.length === 0) return;
    graphStore.temporal.getState().redo();
    syncFromGraph();
  }, [graphStore, syncFromGraph]);

  // Cmd/Ctrl+Z 撤销,Cmd+Shift+Z / Ctrl+Y 重做;输入框 / 代码编辑器(contenteditable)内不劫持。
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if ((key === "z" && event.shiftKey) || key === "y") {
        event.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(null);
  const [renaming, setRenaming] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [agentOpen, setAgentOpen] = React.useState(false);
  const [nodeSearchOpen, setNodeSearchOpen] = React.useState(false);
  const [nodeSearch, setNodeSearch] = React.useState("");
  // While a node is being dragged we pause auto-save: a mid-drag PATCH→refetch would rebuild the
  // graph and interrupt React Flow's drag. The save fires once, right after the drag settles.
  const [dragging, setDragging] = React.useState(false);
  // Drill-in: double-click a loop node to edit its nested body sub-graph in an overlay canvas.
  const [editingLoopId, setEditingLoopId] = React.useState<string | null>(null);
  const rfRef = React.useRef<ReactFlowInstance | null>(null);

  /**
   * 把视口居中到某坐标上。x 方向右移半个检查器宽度(约 150px),让节点落在被检查器
   * 遮挡之外的可视区。用坐标而非 getNode:新加节点此刻还没同步进 React Flow 内部 store,
   * getNode 会取空;而 setCenter 只改视口变换,不依赖节点已登记。
   */
  const focusPosition = React.useCallback((x: number, y: number, duration = 350) => {
    const instance = rfRef.current;
    if (!instance) return;
    const zoom = Math.max(instance.getZoom(), 0.6);
    // +150/zoom:把节点从画布中心再往左推半个检查器宽度,躲开右侧悬浮检查器。
    instance.setCenter(x + 210 / 2 + 150 / zoom, y + 72 / 2, { zoom, duration });
  }, []);

  /** 选中并聚焦某节点(节点搜索用;从当前 graph 取坐标)。 */
  const focusNode = React.useCallback(
    (nodeId: string) => {
      const target = graph.nodes.find((node) => node.id === nodeId);
      if (!target) return;
      setSelectedNodeId(nodeId);
      focusPosition(target.position?.x ?? 0, target.position?.y ?? 0);
    },
    [graph.nodes, focusPosition],
  );

  // 智能体经确认卡改图后 updated_at 变化:画布无本地改动时自动跟进服务端版本。
  const lastSyncedRef = React.useRef(workflow.updated_at);
  // 自己保存引发的那次 refetch 不能重建画布(重建会丢掉 React Flow 的实测尺寸、造成闪烁与
  // 拖拽中断)。不靠比对 updated_at 字符串——两端序列化只要差一点就会误判。
  const selfSaveRef = React.useRef(false);
  React.useEffect(() => {
    if (workflow.updated_at === lastSyncedRef.current) return;
    if (selfSaveRef.current) {
      selfSaveRef.current = false;
      lastSyncedRef.current = workflow.updated_at;
      return;
    }
    // Only mark a revision as synced once it has actually been applied. Marking first meant an
    // agent edit arriving while the canvas was dirty was recorded as seen, never applied, and
    // then overwritten by the pending autosave — the agent's change vanished with nothing said.
    // Left unmarked, it is applied as soon as the local edit saves and `dirty` clears.
    if (!dirty) {
      lastSyncedRef.current = workflow.updated_at;
      const next = structuredClone(workflow.graph as unknown as WorkflowGraph);
      setGraph(next);
      setNodes(toFlowNodes(next, registry));
      setEdges(toFlowEdges(next));
    }
  }, [workflow.updated_at, workflow.graph, dirty, registry]);

  const applyGraph = React.useCallback(
    (next: WorkflowGraph) => {
      setGraph(next);
      setNodes(toFlowNodes(next, registry));
      setEdges(toFlowEdges(next));
      setDirty(true);
    },
    [registry],
  );

  const onNodesChange = React.useCallback(
    (changes: NodeChange[]) => {
      setNodes((current) => applyNodeChanges(changes, current));
      // 位置/删除同步回 graph
      setGraph((current) => {
        let next = current;
        for (const change of changes) {
          if (change.type === "position" && change.position) {
            next = {
              ...next,
              nodes: next.nodes.map((node) =>
                node.id === change.id ? { ...node, position: { x: change.position!.x, y: change.position!.y } } : node,
              ),
            };
          } else if (change.type === "remove") {
            next = {
              ...next,
              nodes: next.nodes.filter((node) => node.id !== change.id),
              edges: next.edges.filter((edge) => edge.source !== change.id && edge.target !== change.id),
            };
          }
        }
        if (next !== current) setDirty(true);
        return next;
      });
    },
    [],
  );

  const onEdgesChange = React.useCallback((changes: EdgeChange[]) => {
    setEdges((current) => applyEdgeChanges(changes, current));
    setGraph((current) => {
      let next = current;
      for (const change of changes) {
        if (change.type === "remove") {
          next = { ...next, edges: next.edges.filter((edge) => edge.id !== change.id) };
        }
      }
      if (next !== current) setDirty(true);
      return next;
    });
  }, []);

  const onConnect = React.useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const srcHandle = connection.sourceHandle ?? undefined;
      const tgtHandle = connection.targetHandle ?? undefined;
      // 数据边:输出接点 out:x → 输入接点 in:y。一个输入只接一条数据边;连上后清字面量交给数据边供值。
      if (srcHandle?.startsWith("out:") && tgtHandle?.startsWith("in:")) {
        const output = srcHandle.slice(4);
        const targetInput = tgtHandle.slice(3);
        const id = `d-${connection.source}-${output}-${connection.target}-${targetInput}`;
        setGraph((current) => {
          const kept = current.edges.filter(
            (edge) => !(edge.kind === "data" && edge.target === connection.target && edge.target_input === targetInput),
          );
          const next: WorkflowGraph = {
            ...current,
            edges: [
              ...kept,
              {
                id,
                source: connection.source!,
                target: connection.target!,
                kind: "data",
                source_output: output,
                target_input: targetInput,
              },
            ],
            nodes: current.nodes.map((node) =>
              node.id === connection.target
                ? {
                    ...node,
                    inputs: Array.from(new Set([...(node.inputs ?? []), targetInput])),
                    config: { ...(node.config ?? {}), [targetInput]: "" },
                  }
                : node,
            ),
          };
          setNodes(toFlowNodes(next, registry));
          setEdges(toFlowEdges(next));
          return next;
        });
        setDirty(true);
        return;
      }
      // 控制边:节点 → 节点(条件分支带 handle)。
      const id = `e-${connection.source}${srcHandle ? `-${srcHandle}` : ""}-${connection.target}`;
      setGraph((current) => {
        if (current.edges.some((edge) => edge.id === id)) return current;
        const next: WorkflowGraph = {
          ...current,
          edges: [
            ...current.edges,
            { id, source: connection.source!, target: connection.target!, source_handle: srcHandle ?? null },
          ],
        };
        setEdges(toFlowEdges(next));
        return next;
      });
      setDirty(true);
    },
    [registry],
  );

  // 连线合法性:禁自环、禁重复、禁成环(拖到一半就给出红色反馈)。
  const isValidConnection = React.useCallback(
    (connection: Connection | Edge) => {
      const source = connection.source ?? "";
      const target = connection.target ?? "";
      if (!source || !target || source === target) return false;
      const handle = ("sourceHandle" in connection ? connection.sourceHandle : undefined) ?? undefined;
      if (
        graph.edges.some(
          (edge) =>
            edge.source === source && edge.target === target && (edge.source_handle ?? undefined) === handle,
        )
      ) {
        return false;
      }
      // 从 target 出发能走回 source 即成环
      const adjacency = new Map<string, string[]>();
      for (const edge of graph.edges) {
        adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
      }
      const queue = [target];
      const seen = new Set<string>();
      while (queue.length) {
        const current = queue.pop()!;
        if (current === source) return false;
        if (seen.has(current)) continue;
        seen.add(current);
        queue.push(...(adjacency.get(current) ?? []));
      }
      return true;
    },
    [graph.edges],
  );

  const addNode = (type: string) => {
    const meta = registry.get(type);
    if (!meta) return;
    if (type === "start" && graph.nodes.some((node) => node.type === "start")) return;
    const base = type.replace(/_/g, "-");
    let index = 1;
    while (graph.nodes.some((node) => node.id === `${base}-${index}`)) index += 1;
    const id = type === "start" && !graph.nodes.some((node) => node.id === "start") ? "start" : `${base}-${index}`;
    const maxX = Math.max(0, ...graph.nodes.map((node) => node.position?.x ?? 0));
    const config: Record<string, unknown> = {};
    for (const [key, spec] of Object.entries(meta.config as Record<string, { type?: string }>)) {
      // "graph"(循环体子图)必须种成空图,种成 "" 会让子画布打开时 body.nodes.length 崩掉。
      config[key] = spec?.type === "object" ? {} : spec?.type === "graph" ? { nodes: [], edges: [] } : "";
    }
    const position = { x: maxX + 240, y: 140 + (graph.nodes.length % 3) * 90 };
    const next: WorkflowGraph = {
      ...graph,
      nodes: [...graph.nodes, { id, type, name: meta.label, position, config }],
    };
    applyGraph(next);
    setSelectedNodeId(id);
    // 新节点排在最右、又会被右侧检查器盖住 → 加完把视口聚焦过去,别让人找不到。
    // 延后两帧 + 瞬时定位(duration 0):applyGraph 会替换整份节点数组触发重挂重测量,
    // 期间的重渲染会打断 setCenter 的 d3 过渡(动画停在起点=看似没动);瞬时定位无过渡可打断,
    // 一旦落定就不会被后续重渲染重置。
    requestAnimationFrame(() => requestAnimationFrame(() => focusPosition(position.x, position.y, 0)));
  };

  const save = useMutation({
    mutationFn: () => updateWorkflow(workflow.id, { graph }),
    onSuccess: (saved) => {
      setDirty(false);
      // Our own save bumps updated_at. Record it as "already synced" so the sync-from-server
      // effect below treats the imminent refetch as our own change and does NOT rebuild the
      // React Flow nodes array. A rebuild drops React Flow's measured dimensions, which re-hides
      // nodes for a frame (visibility:hidden) — during that window a node grab lands on the pane
      // and pans the canvas instead of dragging the node. With auto-save firing after every edit,
      // that window recurred constantly and made nodes feel undraggable.
      lastSyncedRef.current = saved.updated_at;
      selfSaveRef.current = true; // 兜底:即便两端 updated_at 序列化不一致也不重建画布
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
    },
    onError: (error: Error) => toast.error(t("wfSaveFailed"), { description: error.message }),
  });
  // Real-time save (Dify-style): debounce-save the graph whenever it changes, so there's no
  // manual "save" step. A save clears `dirty`; a rapid edit reschedules the pending save.
  const saveRef = React.useRef(save);
  saveRef.current = save;
  // Whether a save is still owed, read by the unmount flush below. A ref, not state, because
  // the cleanup that reads it runs after the last render.
  const pendingSaveRef = React.useRef(false);
  pendingSaveRef.current = dirty;

  React.useEffect(() => {
    if (!dirty || dragging) return;
    const id = window.setTimeout(() => saveRef.current.mutate(), 700);
    return () => window.clearTimeout(id);
  }, [dirty, graph, dragging]);

  // Flush on the way out. The debounce timer is cleared by its own cleanup, so editing a node
  // and then switching workflow, leaving the view, or closing the window inside 700ms threw the
  // edit away — and the 5s poll then repainted the canvas from the server's older graph, so it
  // looked as though the change had undone itself. This editor is keyed by workflow id, so
  // switching workflows unmounts it and is the common way to hit that.
  React.useEffect(() => {
    const flush = () => {
      if (pendingSaveRef.current) saveRef.current.mutate();
    };
    window.addEventListener("beforeunload", flush);
    return () => {
      window.removeEventListener("beforeunload", flush);
      flush();
    };
  }, []);
  const rename = useMutation({
    mutationFn: (name: string) => updateWorkflow(workflow.id, { name }),
    onSuccess: () => {
      setRenaming(false);
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteWorkflow(workflow.id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] }),
  });
  const run = useMutation({
    mutationFn: () => runWorkflow(workflow.id),
    onSuccess: () => {
      toast.success(t("wfRunQueued"));
      void qc.invalidateQueries({ queryKey: ["workflow-runs", workflow.id] });
    },
    onError: (error: Error) => toast.error(t("wfRunFailed"), { description: error.message }),
  });
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null;

  // 就绪度分析:模型/密钥信号在编辑器层拉取(与属性面板共用 queryKey,自动去重),
  // 供画布角标 + 运行前 checklist。只有图里真有对应节点才请求。
  const hasLlm = graph.nodes.some((node) => node.type === "llm");
  const hasGen = graph.nodes.some((node) => node.type === "ai_generate");
  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<Array<{ id: string; name: string; vendor: string }>>("/api/settings/providers"),
    enabled: hasLlm,
  });
  const credentials = useQuery({ queryKey: ["credentials"], queryFn: listCredentials, enabled: hasGen });
  const analysis = React.useMemo(
    () =>
      analyzeWorkflow(graph, registry, {
        providerIds: new Set((providers.data ?? []).map((p) => p.id)),
        providersLoaded: !hasLlm || providers.isSuccess,
        configuredGenProviders: new Set((credentials.data ?? []).filter((c) => c.configured).map((c) => c.provider)),
        credentialsLoaded: !hasGen || credentials.isSuccess,
      }),
    [graph, registry, providers.data, providers.isSuccess, credentials.data, credentials.isSuccess, hasLlm, hasGen],
  );

  // 角标信息塞进节点 data(不动 nodes 状态本身,避免打断拖拽)。
  const displayNodes = React.useMemo(
    () =>
      nodes.map((node) => {
        const nodeIssues = analysis.byNode.get(node.id);
        const severity = analysis.severityByNode.get(node.id);
        const badge =
          nodeIssues && severity
            ? { severity, count: nodeIssues.length, title: nodeIssues.map((i) => issueText(t, i)).join("\n") }
            : null;
        return { ...node, data: { ...node.data, badge } };
      }),
    [nodes, analysis, t],
  );

  return (
    <div className="wf-editor">
      <div className="wf-toolbar">
        <button type="button" className="wf-title" onClick={() => setRenaming(true)} title={t("rename")}>
          <span className="wf-title-icon">
            <WorkflowIcon size={14} />
          </span>
          <span className="wf-title-text">
            <strong>{workflow.name}</strong>
            {/* 保存状态只放工具栏的 wf-save-status:标题里再挂一行「未保存」会随每次
                拖动→自动保存增删一行,撑动整条工具栏导致画布跳一下(闪烁)。 */}
          </span>
        </button>
        <div className="wf-toolbar-actions">
          <Select onValueChange={addNode} value="">
            <SelectTrigger className="wf-add-node" aria-label={t("wfAddNode")}>
              <Plus size={12} />
              <span>{t("wfAddNode")}</span>
            </SelectTrigger>
            <SelectContent>
              {nodeTypes
                .filter((meta) => meta.type !== "start" || !graphHasStart)
                .map((meta) => (
                  <SelectItem key={meta.type} value={meta.type}>
                    {meta.label}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          <Button variant="ghost" size="icon-sm" title={`${t("undo")} ⌘Z`} aria-label={t("undo")} disabled={!canUndo} onClick={undo}>
            <Undo2 size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" title={`${t("redo")} ⇧⌘Z`} aria-label={t("redo")} disabled={!canRedo} onClick={redo}>
            <Redo2 size={14} />
          </Button>
          <div className="wf-toolbar-sep" />
          <Button
            variant={agentOpen ? "secondary" : "outline"}
            size="sm"
            onClick={() => setAgentOpen((value) => !value)}
          >
            <Bot size={13} /> {t("wfAgentTitle")}
          </Button>
          <Popover
            open={nodeSearchOpen}
            onOpenChange={(open) => {
              setNodeSearchOpen(open);
              if (!open) setNodeSearch("");
            }}
          >
            <PopoverTrigger asChild>
              <Button variant="outline" size="icon-sm" aria-label={t("wfNodeSearch")} title={t("wfNodeSearch")}>
                <Search size={14} />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="wf-nodesearch-pop">
              <div className="wf-nodesearch-field">
                <Search size={13} />
                <input
                  autoFocus
                  value={nodeSearch}
                  onChange={(event) => setNodeSearch(event.target.value)}
                  placeholder={t("wfNodeSearchPlaceholder")}
                />
              </div>
              <div className="wf-nodesearch-list">
                {(() => {
                  const query = nodeSearch.trim().toLowerCase();
                  const matches = graph.nodes.filter((node) => {
                    if (!query) return true;
                    const label = (registry.get(node.type)?.label ?? node.type).toLowerCase();
                    return (
                      (node.name || "").toLowerCase().includes(query) ||
                      node.type.toLowerCase().includes(query) ||
                      label.includes(query)
                    );
                  });
                  if (matches.length === 0)
                    return <div className="wf-nodesearch-empty">{t("wfNodeSearchEmpty")}</div>;
                  return matches.map((node) => {
                    const label = registry.get(node.type)?.label ?? node.type;
                    // 未改名时 name 就是类型标签,再补一列类型纯属重复 → 仅改过名才显示类型。
                    const typeSub = node.name && node.name !== label ? label : null;
                    return (
                      <button
                        key={node.id}
                        type="button"
                        className={`wf-nodesearch-row${node.id === selectedNodeId ? " is-active" : ""}`}
                        onClick={() => {
                          focusNode(node.id);
                          setNodeSearchOpen(false);
                          setNodeSearch("");
                        }}
                      >
                        <span className="wf-nodesearch-name">{node.name || label}</span>
                        {typeSub && <span className="wf-nodesearch-type">{typeSub}</span>}
                      </button>
                    );
                  });
                })()}
              </div>
            </PopoverContent>
          </Popover>
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className={`wf-checklist-btn${
                  analysis.errorCount ? " has-error" : analysis.warnCount ? " has-warn" : " ok"
                }`}
              >
                {analysis.errorCount || analysis.warnCount ? <AlertTriangle size={13} /> : <CircleCheck size={13} />}
                <span>{t("wfChecklist")}</span>
                {analysis.errorCount + analysis.warnCount > 0 && (
                  <em className="wf-checklist-count">{analysis.errorCount + analysis.warnCount}</em>
                )}
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="wf-checklist-pop">
              {analysis.issues.length === 0 ? (
                <div className="wf-checklist-ok">
                  <CircleCheck size={14} /> {t("wfChecklistReady")}
                </div>
              ) : (
                <>
                  <div className="wf-checklist-head">
                    {analysis.errorCount
                      ? t("wfChecklistBlocked").replace("{n}", String(analysis.errorCount))
                      : t("wfChecklistWarnOnly").replace("{n}", String(analysis.warnCount))}
                  </div>
                  <div className="wf-checklist-list">
                    {[...analysis.issues]
                      .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "error" ? -1 : 1))
                      .map((issue, i) => (
                        <button
                          key={`${issue.nodeId}-${issue.code}-${i}`}
                          type="button"
                          className={`wf-checklist-row is-${issue.severity}`}
                          onClick={() => setSelectedNodeId(issue.nodeId)}
                        >
                          <AlertTriangle size={12} />
                          <span className="wf-checklist-node">{issue.nodeName}</span>
                          <span className="wf-checklist-msg">{issueText(t, issue)}</span>
                        </button>
                      ))}
                  </div>
                </>
              )}
            </PopoverContent>
          </Popover>
          <div className="wf-toolbar-sep" />
          <span className="wf-save-status" aria-live="polite">
            {save.isPending ? (
              <>
                <Loader2 size={12} className="spin" /> {t("wfSaving")}
              </>
            ) : dirty ? (
              t("wfUnsaved")
            ) : (
              <>
                <Save size={12} /> {t("wfSavedShort")}
              </>
            )}
          </span>
          <Button
            size="sm"
            disabled={run.isPending || dirty || !analysis.runnable}
            title={dirty ? t("wfSaving") : !analysis.runnable ? t("wfRunBlocked") : undefined}
            onClick={() => run.mutate()}
          >
            <Play size={13} /> {t("wfRun")}
          </Button>
          <div className="wf-toolbar-sep" />
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t("wfHistory")}
            title={t("wfHistory")}
            className={showHistory ? "wf-active" : undefined}
            onClick={() => setShowHistory((v) => !v)}
          >
            <History size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" aria-label={t("delete")} onClick={() => setDeleting(true)}>
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      <div className="wf-canvas-wrap">
        <div className="wf-canvas">
          <ReactFlow
            nodes={displayNodes}
            edges={edges}
            nodeTypes={NODE_COMPONENT_TYPES}
            onInit={(instance) => {
              rfRef.current = instance as unknown as ReactFlowInstance;
              // 只在挂载时 fit 一次(切换工作流会因 key 重挂而重跑)。用命令式而非声明式
              // fitView 属性:后者会在每次新增未测量节点时重新 fit,把手动聚焦覆盖掉。
              requestAnimationFrame(() => instance.fitView({ padding: 0.25, maxZoom: 1 }));
            }}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeDragStart={() => setDragging(true)}
            onNodeDragStop={() => setDragging(false)}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            connectionRadius={36}
            connectionLineStyle={{ stroke: "var(--primary)", strokeWidth: 1.5, strokeDasharray: "5 4" }}
            onNodeClick={(_event, node) => setSelectedNodeId(node.id)}
            onNodeDoubleClick={(_event, node) => {
              const g = graph.nodes.find((item) => item.id === node.id);
              if (g && (g.type === "loop_foreach" || g.type === "loop_while")) setEditingLoopId(node.id);
            }}
            onPaneClick={() => setSelectedNodeId(null)}
            defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
            proOptions={{ hideAttribution: false }}
            deleteKeyCode={["Backspace", "Delete"]}
          >
            <Background gap={20} size={1.2} />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap pannable zoomable position="bottom-right" />
          </ReactFlow>
        </div>
        {agentOpen && (
          <WorkflowAgentChat workflowId={workflow.id} workflowName={workflow.name} onClose={() => setAgentOpen(false)} />
        )}
        {showHistory && <WorkflowRunHistory workflowId={workflow.id} onClose={() => setShowHistory(false)} />}
        {editingLoopId &&
          (() => {
            const loopNode = graph.nodes.find((item) => item.id === editingLoopId);
            if (!loopNode) return null;
            return (
              <LoopBodyEditor
                loopNode={loopNode}
                registry={registry}
                nodeTypes={nodeTypes}
                workspaceId={workspaceId}
                onChange={(body) =>
                  applyGraph({
                    ...graph,
                    nodes: graph.nodes.map((item) =>
                      item.id === editingLoopId ? { ...item, config: { ...(item.config ?? {}), body } } : item,
                    ),
                  })
                }
                onClose={() => setEditingLoopId(null)}
              />
            );
          })()}
        {/* 钻进循环体时不渲染外层检查器:它和覆盖层同为 z-index:30 且在 DOM 里更靠后,会盖住
            子画布头部(返回/面包屑/添加节点)。子画布有自己的检查器;外层节点回主流程再编辑。 */}
        {selectedNode && !editingLoopId && (
          <NodeInspector
            node={selectedNode}
            meta={registry.get(selectedNode.type) ?? null}
            graph={graph}
            registry={registry}
            workspaceId={workspaceId}
            onChange={(patch) => {
              applyGraph({
                ...graph,
                nodes: graph.nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node)),
              });
            }}
            onApplyGraph={applyGraph}
            onDelete={() => {
              applyGraph({
                ...graph,
                nodes: graph.nodes.filter((node) => node.id !== selectedNode.id),
                edges: graph.edges.filter(
                  (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id,
                ),
              });
              setSelectedNodeId(null);
            }}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
      </div>

      <RenameDialog
        open={renaming}
        title={t("rename")}
        initialValue={workflow.name}
        onCancel={() => setRenaming(false)}
        onSubmit={(name) => rename.mutate(name)}
      />
      <ConfirmDialog
        open={deleting}
        title={t("deleteConfirmTitle")}
        body={t("wfDeleteBody")}
        onCancel={() => setDeleting(false)}
        onConfirm={() => remove.mutate()}
      />
    </div>
  );
}

interface ConfigSpec {
  type?: string;
  description?: string;
  required?: boolean;
  options?: string[];
}

/** 选中节点的所有上游变量(祖先节点输出 + start 参数),供插入器使用。 */
function upstreamVariables(
  graph: WorkflowGraph,
  nodeId: string,
  registry: Map<string, WorkflowNodeType>,
): string[] {
  const parents = new Map<string, string[]>();
  for (const edge of graph.edges) {
    parents.set(edge.target, [...(parents.get(edge.target) ?? []), edge.source]);
  }
  const ancestors = new Set<string>();
  const queue = [...(parents.get(nodeId) ?? [])];
  while (queue.length) {
    const current = queue.pop()!;
    if (ancestors.has(current)) continue;
    ancestors.add(current);
    queue.push(...(parents.get(current) ?? []));
  }
  const refs: string[] = [];
  for (const node of graph.nodes) {
    if (!ancestors.has(node.id)) continue;
    if (node.type === "start") {
      const params = ((node.config as { params?: Record<string, unknown> })?.params ?? {}) as object;
      for (const key of Object.keys(params)) refs.push(`{{${node.id}.${key}}}`);
    } else {
      for (const output of registry.get(node.type)?.outputs ?? []) refs.push(`{{${node.id}.${output}}}`);
    }
  }
  return refs;
}

/** object(JSON)字段:CodeMirror JSON 编辑,失焦解析回对象;非法给提示不写入。 */
function JsonField({ value, onChange }: { value: unknown; onChange: (parsed: unknown) => void }) {
  const t = useI18n();
  const [text, setText] = React.useState(() => JSON.stringify(value ?? {}, null, 2));
  // 上游(智能体改图)更新时回显,但不打断正在输入:仅当序列化值真变才重置。
  const synced = React.useRef(text);
  React.useEffect(() => {
    const next = JSON.stringify(value ?? {}, null, 2);
    if (next !== synced.current) {
      synced.current = next;
      setText(next);
    }
  }, [value]);
  return (
    <CodeEditor
      value={text}
      language="json"
      minHeight={34}
      gutter={false}
      onChange={setText}
      onBlur={() => {
        try {
          const parsed = JSON.parse(text || "{}");
          synced.current = JSON.stringify(parsed ?? {}, null, 2);
          onChange(parsed);
        } catch {
          toast.error(t("wfBadJson"));
        }
      }}
    />
  );
}

/** code 字段:CodeMirror Python + 上游变量 chip(插到光标处)。 */
function CodeField({
  value,
  onChange,
  variables,
}: {
  value: string;
  onChange: (value: string) => void;
  variables: string[];
}) {
  const t = useI18n();
  const handle = React.useRef<CodeEditorHandle>(null);
  return (
    <>
      <CodeEditor ref={handle} value={value} language="python" minHeight={140} onChange={onChange} />
      {variables.length > 0 && (
        <div className="wf-var-chips">
          {variables.map((ref) => (
            <button
              key={ref}
              type="button"
              className="wf-var-chip"
              title={t("wfInsertVar")}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => handle.current?.insertAtCursor(ref)}
            >
              {ref.replace(/[{}]/g, "")}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

/** Dify 式节点属性浮层:枚举字段用 Select,模板字段带上游变量插入器。 */
/** Drill-in editor for a loop node's nested `body` sub-graph (Dify-style). A self-contained
 *  mini-canvas: add/connect/move/delete/config body nodes; changes flow up via onChange. */
function LoopBodyEditor({
  loopNode,
  registry,
  nodeTypes,
  workspaceId,
  onChange,
  onClose,
}: {
  loopNode: WorkflowGraph["nodes"][number];
  registry: Map<string, WorkflowNodeType>;
  nodeTypes: WorkflowNodeType[];
  workspaceId: string;
  onChange: (body: WorkflowGraph) => void;
  onClose: () => void;
}) {
  const t = useI18n();
  // config.body may be missing, or "" (addNode seeds unknown field types with an empty string) —
  // anything not shaped like a graph must become an empty one, or body.nodes.length blows up the
  // whole app on open.
  const initialBody = React.useMemo<WorkflowGraph>(() => {
    const raw = loopNode.config?.body as unknown;
    return raw && typeof raw === "object" && Array.isArray((raw as WorkflowGraph).nodes)
      ? (raw as WorkflowGraph)
      : { nodes: [], edges: [] };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seed once; body state owns it after
  }, []);
  const [body, setBody] = React.useState<WorkflowGraph>(() => structuredClone(initialBody));
  const [nodes, setNodes] = React.useState<Node[]>(() => toFlowNodes(initialBody, registry));
  const [edges, setEdges] = React.useState<Edge[]>(() => toFlowEdges(initialBody));
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const commit = React.useCallback(
    (next: WorkflowGraph) => {
      setBody(next);
      setNodes(toFlowNodes(next, registry));
      setEdges(toFlowEdges(next));
      onChange(next);
    },
    [registry, onChange],
  );

  const onNodesChange = React.useCallback(
    (changes: NodeChange[]) => {
      setNodes((current) => applyNodeChanges(changes, current));
      setBody((current) => {
        let next = current;
        for (const change of changes) {
          if (change.type === "position" && change.position) {
            next = {
              ...next,
              nodes: next.nodes.map((node) =>
                node.id === change.id ? { ...node, position: { x: change.position!.x, y: change.position!.y } } : node,
              ),
            };
          } else if (change.type === "remove") {
            next = {
              ...next,
              nodes: next.nodes.filter((node) => node.id !== change.id),
              edges: next.edges.filter((edge) => edge.source !== change.id && edge.target !== change.id),
            };
          }
        }
        if (next !== current) onChange(next);
        return next;
      });
    },
    [onChange],
  );

  const onEdgesChange = React.useCallback(
    (changes: EdgeChange[]) => {
      setEdges((current) => applyEdgeChanges(changes, current));
      setBody((current) => {
        let next = current;
        for (const change of changes) {
          if (change.type === "remove") next = { ...next, edges: next.edges.filter((edge) => edge.id !== change.id) };
        }
        if (next !== current) onChange(next);
        return next;
      });
    },
    [onChange],
  );

  const onConnect = React.useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const srcHandle = connection.sourceHandle ?? undefined;
      const tgtHandle = connection.targetHandle ?? undefined;
      let next: WorkflowGraph;
      if (srcHandle?.startsWith("out:") && tgtHandle?.startsWith("in:")) {
        const output = srcHandle.slice(4);
        const targetInput = tgtHandle.slice(3);
        const kept = body.edges.filter(
          (edge) => !(edge.kind === "data" && edge.target === connection.target && edge.target_input === targetInput),
        );
        next = {
          ...body,
          edges: [
            ...kept,
            { id: `d-${connection.source}-${output}-${connection.target}-${targetInput}`, source: connection.source, target: connection.target, kind: "data", source_output: output, target_input: targetInput },
          ],
          nodes: body.nodes.map((node) =>
            node.id === connection.target
              ? { ...node, inputs: Array.from(new Set([...(node.inputs ?? []), targetInput])), config: { ...(node.config ?? {}), [targetInput]: "" } }
              : node,
          ),
        };
      } else {
        const id = `e-${connection.source}${srcHandle ? `-${srcHandle}` : ""}-${connection.target}`;
        if (body.edges.some((edge) => edge.id === id)) return;
        next = { ...body, edges: [...body.edges, { id, source: connection.source, target: connection.target, source_handle: srcHandle ?? null }] };
      }
      commit(next);
    },
    [body, commit],
  );

  const addNode = (type: string) => {
    const meta = registry.get(type);
    if (!meta || type === "start") return;
    const base = type.replace(/_/g, "-");
    let index = 1;
    while (body.nodes.some((node) => node.id === `${base}-${index}`)) index += 1;
    const maxX = Math.max(0, ...body.nodes.map((node) => node.position?.x ?? 0));
    const config: Record<string, unknown> = {};
    for (const [key, spec] of Object.entries(meta.config as Record<string, { type?: string }>)) {
      // "graph"(循环体子图)必须种成空图,种成 "" 会让子画布打开时 body.nodes.length 崩掉。
      config[key] = spec?.type === "object" ? {} : spec?.type === "graph" ? { nodes: [], edges: [] } : "";
    }
    commit({
      ...body,
      nodes: [
        ...body.nodes,
        { id: `${base}-${index}`, type, name: meta.label, position: { x: maxX + 240, y: 140 + (body.nodes.length % 3) * 90 }, config },
      ],
    });
  };

  const selectedNode = selectedId ? (body.nodes.find((node) => node.id === selectedId) ?? null) : null;

  return (
    <div className="wf-loop-overlay">
      <div className="wf-loop-head">
        <button type="button" className="wf-loop-back" onClick={onClose}>
          <ArrowLeft size={14} /> {t("wfLoopBack")}
        </button>
        <span className="wf-loop-crumb">
          <Repeat size={13} /> {loopNode.name} · {t("wfLoopBody")}
        </span>
        <Select onValueChange={addNode} value="">
          <SelectTrigger className="wf-add-node" aria-label={t("wfAddNode")}>
            <Plus size={12} />
            <span>{t("wfAddNode")}</span>
          </SelectTrigger>
          <SelectContent>
            {nodeTypes
              .filter((meta) => meta.type !== "start")
              .map((meta) => (
                <SelectItem key={meta.type} value={meta.type}>
                  {meta.label}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </div>
      <div className="wf-loop-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_COMPONENT_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_event, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
          defaultEdgeOptions={DEFAULT_EDGE_OPTIONS}
          deleteKeyCode={["Backspace", "Delete"]}
          onInit={(instance) => requestAnimationFrame(() => instance.fitView({ padding: 0.3, maxZoom: 1 }))}
        >
          <Background gap={20} size={1.2} />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>
        {body.nodes.length === 0 && <div className="wf-loop-empty">{t("wfLoopEmptyHint")}</div>}
        {selectedNode && (
          <NodeInspector
            node={selectedNode}
            meta={registry.get(selectedNode.type) ?? null}
            graph={body}
            registry={registry}
            workspaceId={workspaceId}
            onChange={(patch) =>
              commit({ ...body, nodes: body.nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node)) })
            }
            onApplyGraph={(next) => commit(next)}
            onDelete={() => {
              commit({
                ...body,
                nodes: body.nodes.filter((node) => node.id !== selectedNode.id),
                edges: body.edges.filter((edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id),
              });
              setSelectedId(null);
            }}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    </div>
  );
}

function NodeInspector({
  node,
  meta,
  graph,
  registry,
  workspaceId,
  onChange,
  onApplyGraph,
  onDelete,
  onClose,
}: {
  node: WorkflowGraph["nodes"][number];
  meta: WorkflowNodeType | null;
  graph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  workspaceId: string;
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>) => void;
  onApplyGraph: (next: WorkflowGraph) => void;
  onDelete?: () => void;
  onClose?: () => void;
}) {
  const t = useI18n();
  const config = (node.config ?? {}) as Record<string, unknown>;
  const specs = Object.entries((meta?.config ?? {}) as Record<string, ConfigSpec>);
  const fieldRefs = React.useRef<Record<string, HTMLTextAreaElement | null>>({});
  // 每字段的输入方式:手动填写 vs 连接上游输出(ComfyUI 式)。默认从值推断(纯引用=连接)。
  const variables = React.useMemo(
    () => upstreamVariables(graph, node.id, registry),
    [graph, node.id, registry],
  );

  // 失效引用:本节点配置里引用了图中已不存在的节点(通常是上游被删)。
  const staleRefs = React.useMemo(() => {
    const ids = new Set(graph.nodes.map((n) => n.id));
    const found: Array<{ key: string; ref: string }> = [];
    for (const [key, val] of Object.entries(node.config ?? {})) {
      for (const { ref, sourceId } of extractRefs(val)) {
        if (!ids.has(sourceId) && !found.some((f) => f.key === key && f.ref === ref)) {
          found.push({ key, ref });
        }
      }
    }
    return found;
  }, [node.config, graph.nodes]);

  // 动态选项源:按需拉取,只有对应节点类型选中时才请求。
  const providers = useQuery({
    queryKey: ["provider-profiles"],
    queryFn: () => api<Array<{ id: string; name: string; vendor: string }>>("/api/settings/providers"),
    enabled: node.type === "llm",
  });
  const pluginTools = useQuery({
    queryKey: ["plugin-tools"],
    queryFn: () => api<Array<{ plugin_id: string; plugin_name: string; tool_name: string }>>("/api/plugins/tools"),
    enabled: node.type === "plugin_tool",
  });
  const publishAccounts = useQuery({
    queryKey: ["publish-accounts", workspaceId],
    queryFn: () => listPublishAccounts(workspaceId),
    enabled: node.type === "publish",
  });
  const generationModels = useQuery({
    queryKey: ["generation-models"],
    queryFn: () => api<Array<{ id: string; provider: string; model: string; kind: string }>>("/api/generation/models"),
    enabled: node.type === "ai_generate",
  });
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: listCredentials,
    enabled: node.type === "ai_generate",
  });
  const voices = useQuery({
    queryKey: ["workflow-voices", workspaceId],
    queryFn: () => listVoices(workspaceId),
    enabled: node.type === "synthesize_speech",
  });
  // 强类型 asset 字段(如 素材转写.asset_id)手动模式下,给工作区素材下拉,免手填 UUID。
  const hasAssetField = specs.some(([key]) => inputType(node.type, key) === "asset");
  const assets = useQuery({
    queryKey: ["workflow-assets", workspaceId],
    queryFn: () => listAssets(workspaceId),
    enabled: hasAssetField,
  });
  // 知识库检索节点:dataset_id 走知识库下拉。
  const kbDatasets = useQuery({
    queryKey: ["kb-datasets", workspaceId],
    queryFn: () => api<Array<{ id: string; name: string }>>(`/api/kb/datasets?workspace_id=${workspaceId}`),
    enabled: node.type === "kb_search",
  });

  // 绑定校验:节点依赖的模型/服务没配好(空列表)或引用已失效(指向不存在的项)→ 顶部给提醒 + 配置入口。
  const bindingNotice = ((): { message: string; section: string; error?: boolean } | null => {
    if (node.type === "llm") {
      const list = providers.data ?? [];
      if (providers.isSuccess && list.length === 0) return { message: t("wfNoProviders"), section: "providers" };
      const pid = config.profile_id;
      if (pid && providers.isSuccess && !list.some((p) => p.id === pid))
        return { message: t("wfProviderMissing"), section: "providers", error: true };
    }
    if (node.type === "ai_generate") {
      // 生成模型目录始终有内置项;是否可用取决于该服务商的密钥是否配好(credentials)。
      const configured = new Set((credentials.data ?? []).filter((c) => c.configured).map((c) => c.provider));
      const chosenProvider = config.provider as string | undefined;
      if (chosenProvider && credentials.isSuccess && !configured.has(chosenProvider))
        return { message: t("wfGenModelMissing"), section: "providers", error: true };
      const models = generationModels.data ?? [];
      const anyUsable = models.some((g) => configured.has(g.provider));
      if (credentials.isSuccess && generationModels.isSuccess && !anyUsable)
        return { message: t("wfNoGenModels"), section: "providers" };
    }
    return null;
  })();

  // Esc 收起检查器 —— 输入框/代码编辑器里不劫持(那里 Esc 另有用途)。
  React.useEffect(() => {
    if (!onClose) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const setConfig = (key: string, value: unknown) => onChange({ config: { ...config, [key]: value } });

  // 重新指向:把某字段里的失效引用整体替换为新引用(空串=移除该引用)。
  const repoint = (key: string, oldRef: string, newRef: string) => {
    setConfig(key, String(config[key] ?? "").split(oldRef).join(newRef));
  };

  // 连接态字段(node.inputs)+ 数据边管理。
  const connectedInputs = node.inputs ?? [];
  // 本节点的后代(顺边正向可达),绑数据边时排除它们避免成环。
  const descendants = React.useMemo(() => {
    const adjacency = new Map<string, string[]>();
    for (const edge of graph.edges) {
      adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
    }
    const seen = new Set<string>();
    const queue = [...(adjacency.get(node.id) ?? [])];
    while (queue.length) {
      const current = queue.pop()!;
      if (seen.has(current)) continue;
      seen.add(current);
      queue.push(...(adjacency.get(current) ?? []));
    }
    return seen;
  }, [graph.edges, node.id]);
  // 可绑定来源:任意非后代、非自身节点的具体输出(数据边本身即建立依赖/排序)。
  const upstreamOptions = graph.nodes.flatMap((source) => {
    if (source.id === node.id || descendants.has(source.id)) return [];
    return (registry.get(source.type)?.outputs ?? [])
      .filter((output) => !output.startsWith("*"))
      .map((output) => ({ ref: `{{${source.id}.${output}}}`, sourceId: source.id, output }));
  });
  const dataEdgeFor = (key: string) =>
    graph.edges.find((edge) => edge.kind === "data" && edge.target === node.id && edge.target_input === key) ?? null;

  // 切换字段的连接态:连接=进 inputs;断开=移出 inputs 并删对应数据边。
  const setConnected = (key: string, connected: boolean) => {
    const inputs = new Set(connectedInputs);
    if (connected) inputs.add(key);
    else inputs.delete(key);
    onApplyGraph({
      ...graph,
      edges: connected
        ? graph.edges
        : graph.edges.filter(
            (edge) => !(edge.kind === "data" && edge.target === node.id && edge.target_input === key),
          ),
      nodes: graph.nodes.map((n) => (n.id === node.id ? { ...n, inputs: [...inputs] } : n)),
    });
  };

  // 绑定输入到某上游输出:建/换数据边,清字面量交给数据边供值。
  const bindInput = (key: string, sourceId: string, output: string) => {
    const id = `d-${sourceId}-${output}-${node.id}-${key}`;
    onApplyGraph({
      ...graph,
      edges: [
        ...graph.edges.filter((edge) => !(edge.kind === "data" && edge.target === node.id && edge.target_input === key)),
        { id, source: sourceId, target: node.id, kind: "data" as const, source_output: output, target_input: key },
      ],
      nodes: graph.nodes.map((n) =>
        n.id === node.id
          ? { ...n, inputs: [...new Set([...connectedInputs, key])], config: { ...(n.config ?? {}), [key]: "" } }
          : n,
      ),
    });
  };

  const insertVariable = (key: string, ref: string) => {
    const el = fieldRefs.current[key];
    const current = String(config[key] ?? "");
    if (!el) {
      setConfig(key, current + ref);
      return;
    }
    const start = el.selectionStart ?? current.length;
    const end = el.selectionEnd ?? current.length;
    setConfig(key, current.slice(0, start) + ref + current.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = start + ref.length;
    });
  };

  /** (nodeType, key) → 动态下拉选项;返回 null 表示该字段不是动态选择。 */
  const dynamicOptions = (key: string): Array<{ value: string; label: string }> | null => {
    if (node.type === "llm" && key === "profile_id") {
      return (providers.data ?? []).map((p) => ({ value: p.id, label: `${p.name} (${p.vendor})` }));
    }
    if (node.type === "plugin_tool" && key === "plugin_id") {
      const seen = new Map<string, string>();
      for (const tool of pluginTools.data ?? []) seen.set(tool.plugin_id, tool.plugin_name);
      return [...seen].map(([value, label]) => ({ value, label }));
    }
    if (node.type === "plugin_tool" && key === "tool_name") {
      return (pluginTools.data ?? [])
        .filter((tool) => !config.plugin_id || tool.plugin_id === config.plugin_id)
        .map((tool) => ({ value: tool.tool_name, label: tool.tool_name }));
    }
    if (node.type === "publish" && key === "account_id") {
      return (publishAccounts.data ?? []).map((account) => ({ value: account.id, label: account.name }));
    }
    if (node.type === "kb_search" && key === "dataset_id") {
      return (kbDatasets.data ?? []).map((ds) => ({ value: ds.id, label: ds.name }));
    }
    if (node.type === "synthesize_speech" && key === "voice_id") {
      return (voices.data ?? []).map((voice) => ({ value: voice.id, label: voice.name }));
    }
    // asset 型字段:工作区素材下拉(label 用素材名,回退原始文件名)。
    if (inputType(node.type, key) === "asset") {
      return (assets.data ?? []).map((asset) => ({
        value: asset.id,
        label: asset.name || asset.original_filename,
      }));
    }
    return null;
  };

  return (
    <aside className="wf-inspector panel" aria-label={node.name || meta?.label || node.type}>
      <div className="panel-head wf-inspector-head">
        <span className={`wf-node-icon wf-icon-${node.type} wf-inspector-icon`}>
          {NODE_ICONS[node.type] ?? <Type size={13} />}
        </span>
        <div className="wf-inspector-heading">
          {/* 节点名直接在头部内联编辑(Dify 式),不再单列一个"节点名称"字段。 */}
          <input
            className="wf-inspector-name"
            value={node.name ?? ""}
            placeholder={meta?.label ?? node.type}
            aria-label={t("wfNodeName")}
            onChange={(event) => onChange({ name: event.target.value })}
          />
          {/* 名称输入的 placeholder 已是类型名;仅在改过名(与类型不同)时才补一行类型。 */}
          {node.name && node.name !== (meta?.label ?? node.type) && <small>{meta?.label ?? node.type}</small>}
        </div>
        {onDelete && (
          <button type="button" className="inspector-delete" aria-label={t("delete")} onClick={onDelete}>
            <Trash2 size={13} />
          </button>
        )}
        {onClose && (
          <button type="button" className="inspector-close" aria-label={t("close")} title={`${t("close")} (Esc)`} onClick={onClose}>
            <X size={14} />
          </button>
        )}
      </div>
      <div className="wf-inspector-body">
        {meta && <p className="wf-node-desc">{meta.description}</p>}
        {bindingNotice && (
          <ConfigNotice
            message={bindingNotice.message}
            actionLabel={t("wfGoConfigure")}
            section={bindingNotice.section}
            tone={bindingNotice.error ? "error" : "warn"}
          />
        )}
        {staleRefs.length > 0 && (
          <div className="wf-stale-refs">
            <span className="wf-stale-title">
              <AlertTriangle size={12} /> {t("wfStaleRefsTitle")}
            </span>
            {staleRefs.map(({ key, ref }) => (
              <div className="wf-stale-row" key={`${key}-${ref}`}>
                <code className="wf-stale-chip">{ref}</code>
                <Popover>
                  <PopoverTrigger asChild>
                    <button type="button" className="wf-stale-repoint">
                      {t("wfRepoint")}
                    </button>
                  </PopoverTrigger>
                  <PopoverContent align="end" className="wf-repoint-pop">
                    {variables.map((valid) => (
                      <button
                        key={valid}
                        type="button"
                        className="wf-repoint-opt"
                        onClick={() => repoint(key, ref, valid)}
                      >
                        {valid.replace(/[{}]/g, "")}
                      </button>
                    ))}
                    <button
                      type="button"
                      className="wf-repoint-opt danger"
                      onClick={() => repoint(key, ref, "")}
                    >
                      {t("wfRemoveRef")}
                    </button>
                  </PopoverContent>
                </Popover>
              </div>
            ))}
          </div>
        )}
        {node.type === "ai_generate" && (
          <div className="wf-field">
            <span>{t("wfModelPreset")}</span>
            <Select
              value=""
              onValueChange={(id) => {
                const model = (generationModels.data ?? []).find((item) => item.id === id);
                if (model) {
                  onChange({ config: { ...config, provider: model.provider, model: model.model, kind: model.kind } });
                }
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder={t("wfModelPresetHint")} />
              </SelectTrigger>
              <SelectContent>
                {(generationModels.data ?? []).map((model) => (
                  <SelectItem key={model.id} value={model.id}>
                    {model.model} · {model.kind}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        {node.type === "llm" && (
          <div className="wf-field">
            <span>{t("wfLlmPreset")}</span>
            <Select
              value={(config.preset as string) || "balanced"}
              onValueChange={(next) => setConfig("preset", next)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="precise">{t("wfPresetPrecise")}</SelectItem>
                <SelectItem value="balanced">{t("wfPresetBalanced")}</SelectItem>
                <SelectItem value="creative">{t("wfPresetCreative")}</SelectItem>
              </SelectContent>
            </Select>
            <small>
              {config.preset === "precise"
                ? t("wfPresetPreciseHint")
                : config.preset === "creative"
                  ? t("wfPresetCreativeHint")
                  : t("wfPresetBalancedHint")}
            </small>
          </div>
        )}
        {specs
          .filter(([key]) => !(node.type === "llm" && key === "preset"))
          .map(([key, spec]) => {
          // 循环体是内嵌子图(graph 类型):不铺原始 JSON 文本框,给个只读概览(子画布编辑见 L3)。
          if (spec?.type === "graph") {
            const bodyNodes = ((config[key] as { nodes?: unknown[] } | undefined)?.nodes ?? []).length;
            return (
              <div className="wf-field" key={key}>
                <label>{t("wfLoopBody")}</label>
                <div className="wf-body-summary">{t("wfLoopBodyNote").replace("{n}", String(bodyNodes))}</div>
              </div>
            );
          }
          const value = config[key];
          const isObject = spec?.type === "object";
          const options = spec?.options
            ? spec.options.map((option) => ({ value: option, label: option }))
            : dynamicOptions(key);
          const labelKey = FIELD_LABEL_KEYS[key];
          // ComfyUI 式:非 object 字段都可切到"连接"(暴露输入接点,再从画布拖数据边或下拉选源)。
          const canConnect = !isObject;
          const connected = canConnect && connectedInputs.includes(key);
          const boundEdge = connected ? dataEdgeFor(key) : null;
          const boundValue = boundEdge ? `${boundEdge.source}.${boundEdge.source_output}` : "";
          return (
            <div className="wf-field" key={key}>
              <span>
                {labelKey ? t(labelKey) : key}
                {spec?.required ? <em className="wf-field-req">*</em> : null}
                {canConnect && (
                  <button
                    type="button"
                    className={`wf-field-mode${connected ? " is-ref" : ""}`}
                    title={t("wfInputModeHint")}
                    onClick={(event) => {
                      event.preventDefault();
                      setConnected(key, !connected);
                    }}
                  >
                    {connected ? <Link2 size={11} /> : <PenLine size={11} />}
                    {connected ? t("wfInputRef") : t("wfInputManual")}
                  </button>
                )}
              </span>
              {connected ? (
                <div className="wf-ref-slot">
                  <Select
                    value={boundValue}
                    onValueChange={(next) => {
                      const dot = next.indexOf(".");
                      bindInput(key, next.slice(0, dot), next.slice(dot + 1));
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={t("wfPickUpstream")} />
                    </SelectTrigger>
                    <SelectContent>
                      {upstreamOptions.map((option) => (
                        <SelectItem key={option.ref} value={`${option.sourceId}.${option.output}`}>
                          {option.sourceId}.{option.output}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              ) : options ? (
                <Select value={String(value ?? "")} onValueChange={(next) => setConfig(key, next)}>
                  <SelectTrigger>
                    <SelectValue placeholder={t("wfPickOption")} />
                  </SelectTrigger>
                  <SelectContent>
                    {options.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : isObject ? (
                <JsonField value={value} onChange={(parsed) => setConfig(key, parsed)} />
              ) : spec?.type === "code" ? (
                <CodeField value={String(value ?? "")} onChange={(next) => setConfig(key, next)} variables={variables} />
              ) : (
                <VarTextarea
                  textareaRef={(el) => {
                    fieldRefs.current[key] = el;
                  }}
                  rows={spec?.type === "template" ? 2 : 1}
                  value={String(value ?? "")}
                  onChange={(next) => setConfig(key, next)}
                  variables={variables}
                />
              )}
              {!connected && spec?.type === "template" && variables.length > 0 && (
                <div className="wf-var-chips">
                  {variables.map((ref) => (
                    <button
                      key={ref}
                      type="button"
                      className="wf-var-chip"
                      title={t("wfInsertVar")}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => insertVariable(key, ref)}
                    >
                      {ref.replace(/[{}]/g, "")}
                    </button>
                  ))}
                </div>
              )}
              {spec?.description && <small>{spec.description}</small>}
            </div>
          );
        })}
        {meta && (
          <div className="wf-node-outputs">
            <span>{t("wfOutputs")}</span>
            <div className="wf-out-chips">
              {meta.outputs.map((output) => {
                const ref = `{{${node.id}.${output}}}`;
                return (
                  <button
                    key={output}
                    type="button"
                    className="wf-out-chip"
                    title={t("wfCopyRef")}
                    onClick={() => {
                      void navigator.clipboard.writeText(ref);
                      toast.success(t("wfRefCopied"), { description: ref });
                    }}
                  >
                    {ref}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
