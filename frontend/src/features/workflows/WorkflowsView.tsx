import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlignLeft,
  AlertTriangle,
  BookOpen,
  Bot,
  CircleCheck,
  Code2,
  Download,
  Flag,
  GitBranch,
  Globe,
  Link2,
  Loader2,
  Mic,
  Pencil,
  PenLine,
  Play,
  Plus,
  Rocket,
  Save,
  Sparkles,
  Trash2,
  Type,
  Wand2,
  Workflow as WorkflowIcon,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";

import {
  api,
  createWorkflow,
  deleteWorkflow,
  fetchWorkflowNodeTypes,
  listCredentials,
  listPublishAccounts,
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
import { analyzeWorkflow, extractRefs, type NodeIssue } from "@/features/workflows/analyze";

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
          <small>{d.typeLabel}</small>
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
                <Handle id={`in:${key}`} type="target" position={Position.Left} className="wf-socket" />
                <span className="wf-io-label">{FIELD_LABEL_KEYS[key] ? t(FIELD_LABEL_KEYS[key]) : key}</span>
              </div>
            ))}
          </div>
          <div className="wf-io-col out">
            {outputs.map((output) => (
              <div className="wf-io-row" key={output}>
                <span className="wf-io-label">{output}</span>
                <Handle id={`out:${output}`} type="source" position={Position.Right} className="wf-socket" />
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
    onSuccess: () => toast.success(t("wfRunQueued")),
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
    deletable: node.type !== "start",
  }));
}

function toFlowEdges(graph: WorkflowGraph): Edge[] {
  return (graph.edges ?? []).map((edge) => {
    // 数据边:接输出接点 out:x → 输入接点 in:y。蓝色流动虚线,不带箭头(终点是接点)。
    if (edge.kind === "data") {
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.source_output ? `out:${edge.source_output}` : undefined,
        targetHandle: edge.target_input ? `in:${edge.target_input}` : undefined,
        className: "wf-edge-data",
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
    default:
      return issue.code;
  }
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

  // graph 是唯一事实:configs/names 存这里;React Flow 只管几何与选中。
  const [graph, setGraph] = React.useState<WorkflowGraph>(() => structuredClone(workflow.graph as unknown as WorkflowGraph));
  const [nodes, setNodes] = React.useState<Node[]>(() => toFlowNodes(workflow.graph as unknown as WorkflowGraph, registry));
  const [edges, setEdges] = React.useState<Edge[]>(() => toFlowEdges(workflow.graph as unknown as WorkflowGraph));
  const [dirty, setDirty] = React.useState(false);
  const [selectedNodeId, setSelectedNodeId] = React.useState<string | null>(null);
  const [renaming, setRenaming] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [agentOpen, setAgentOpen] = React.useState(false);

  // 智能体经确认卡改图后 updated_at 变化:画布无本地改动时自动跟进服务端版本。
  const lastSyncedRef = React.useRef(workflow.updated_at);
  React.useEffect(() => {
    if (workflow.updated_at === lastSyncedRef.current) return;
    lastSyncedRef.current = workflow.updated_at;
    if (!dirty) {
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
    const base = type.replace(/_/g, "-");
    let index = 1;
    while (graph.nodes.some((node) => node.id === `${base}-${index}`)) index += 1;
    const id = `${base}-${index}`;
    const maxX = Math.max(0, ...graph.nodes.map((node) => node.position?.x ?? 0));
    const config: Record<string, unknown> = {};
    for (const [key, spec] of Object.entries(meta.config as Record<string, { type?: string }>)) {
      config[key] = spec?.type === "object" ? {} : "";
    }
    const next: WorkflowGraph = {
      ...graph,
      nodes: [
        ...graph.nodes,
        { id, type, name: meta.label, position: { x: maxX + 240, y: 140 + (graph.nodes.length % 3) * 90 }, config },
      ],
    };
    applyGraph(next);
    setSelectedNodeId(id);
  };

  const save = useMutation({
    mutationFn: () => updateWorkflow(workflow.id, { graph }),
    onSuccess: () => {
      setDirty(false);
      toast.success(t("wfSaved"));
      void qc.invalidateQueries({ queryKey: ["workflows", workspaceId] });
    },
    onError: (error: Error) => toast.error(t("wfSaveFailed"), { description: error.message }),
  });
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
    onSuccess: () => toast.success(t("wfRunQueued")),
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
            <small>
              {t("wfNodeCount").replace("{n}", String(graph.nodes.length))}
              {dirty ? ` · ${t("wfUnsaved")}` : ""}
            </small>
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
                .filter((meta) => meta.type !== "start")
                .map((meta) => (
                  <SelectItem key={meta.type} value={meta.type}>
                    {meta.label}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
          <Button
            variant={agentOpen ? "secondary" : "outline"}
            size="sm"
            onClick={() => setAgentOpen((value) => !value)}
          >
            <Bot size={13} /> {t("wfAgentTitle")}
          </Button>
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
          <Button variant="outline" size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            <Save size={13} /> {t("save")}
          </Button>
          <Button
            size="sm"
            disabled={run.isPending || dirty || !analysis.runnable}
            title={dirty ? t("wfSaveFirst") : !analysis.runnable ? t("wfRunBlocked") : undefined}
            onClick={() => run.mutate()}
          >
            <Play size={13} /> {t("wfRun")}
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
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            isValidConnection={isValidConnection}
            connectionRadius={36}
            connectionLineStyle={{ stroke: "var(--primary)", strokeWidth: 1.5, strokeDasharray: "5 4" }}
            onNodeClick={(_event, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            fitView
            fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
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
        {selectedNode && (
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
            onDelete={
              selectedNode.type === "start"
                ? undefined
                : () => {
                    applyGraph({
                      ...graph,
                      nodes: graph.nodes.filter((node) => node.id !== selectedNode.id),
                      edges: graph.edges.filter(
                        (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id,
                      ),
                    });
                    setSelectedNodeId(null);
                  }
            }
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
      minHeight={72}
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
function NodeInspector({
  node,
  meta,
  graph,
  registry,
  workspaceId,
  onChange,
  onApplyGraph,
  onDelete,
}: {
  node: WorkflowGraph["nodes"][number];
  meta: WorkflowNodeType | null;
  graph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  workspaceId: string;
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>) => void;
  onApplyGraph: (next: WorkflowGraph) => void;
  onDelete?: () => void;
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
          <small>{meta?.label ?? node.type}</small>
        </div>
        {onDelete && (
          <button type="button" className="inspector-delete" aria-label={t("delete")} onClick={onDelete}>
            <Trash2 size={13} />
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
          <label className="wf-field">
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
          </label>
        )}
        {node.type === "llm" && (
          <label className="wf-field">
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
          </label>
        )}
        {specs
          .filter(([key]) => !(node.type === "llm" && key === "preset"))
          .map(([key, spec]) => {
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
            <label className="wf-field" key={key}>
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
            </label>
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
