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
  BookOpen,
  Bot,
  Code2,
  Download,
  Flag,
  GitBranch,
  Globe,
  Loader2,
  Mic,
  Pencil,
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
import { Button } from "@/components/ui/button";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { VarTextarea } from "@/features/workflows/VarTextarea";
import { WorkflowAgentChat } from "@/features/workflows/WorkflowAgentChat";

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
}

/** 画布节点:语义色图标 + 名称 + 类型标签,全平面卡片。
    条件节点右侧是「真/假」两个分支端点,其余节点单一出口。 */
function WfNode({ data, selected }: NodeProps) {
  const d = data as WfNodeData;
  const isCondition = d.nodeType === "condition";
  return (
    <div className={selected ? "wf-node selected" : "wf-node"} data-node-type={d.nodeType}>
      {d.nodeType !== "start" && <Handle type="target" position={Position.Left} className="wf-handle" />}
      <span className={`wf-node-icon wf-icon-${d.nodeType}`}>{NODE_ICONS[d.nodeType] ?? <Type size={13} />}</span>
      <span className="wf-node-text">
        <strong>{d.label}</strong>
        <small>{d.typeLabel}</small>
      </span>
      {isCondition ? (
        <>
          <Handle
            id="true"
            type="source"
            position={Position.Right}
            className="wf-handle wf-handle-true"
            style={{ top: "32%" }}
          />
          <Handle
            id="false"
            type="source"
            position={Position.Right}
            className="wf-handle wf-handle-false"
            style={{ top: "68%" }}
          />
          <span className="wf-branch-label true">真</span>
          <span className="wf-branch-label false">假</span>
        </>
      ) : (
        <Handle type="source" position={Position.Right} className="wf-handle" />
      )}
    </div>
  );
}

const NODE_COMPONENT_TYPES = { wf: WfNode };

/** 连线统一带闭合箭头,方向一目了然。 */
const DEFAULT_EDGE_OPTIONS = {
  markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15 },
};

export function WorkflowsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [menuRenaming, setMenuRenaming] = React.useState<Workflow | null>(null);
  const [menuDeleting, setMenuDeleting] = React.useState<Workflow | null>(null);

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
            <EmptyState icon={<WorkflowIcon size={22} />} title={t("wfEmptyTitle")} body={t("wfEmptyBody")} />
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
    } satisfies WfNodeData,
    deletable: node.type !== "start",
  }));
}

function toFlowEdges(graph: WorkflowGraph): Edge[] {
  return (graph.edges ?? []).map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.source_handle ?? undefined,
    label: edge.source_handle === "true" ? "真" : edge.source_handle === "false" ? "假" : undefined,
    className: edge.source_handle ? `wf-edge-${edge.source_handle}` : undefined,
  }));
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
      const handle = connection.sourceHandle ?? undefined;
      const id = `e-${connection.source}${handle ? `-${handle}` : ""}-${connection.target}`;
      setGraph((current) => {
        if (current.edges.some((edge) => edge.id === id)) return current;
        const next: WorkflowGraph = {
          ...current,
          edges: [
            ...current.edges,
            { id, source: connection.source!, target: connection.target!, source_handle: handle ?? null },
          ],
        };
        setEdges(toFlowEdges(next));
        return next;
      });
      setDirty(true);
    },
    [],
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
          <Button variant="outline" size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            <Save size={13} /> {t("save")}
          </Button>
          <Button size="sm" disabled={run.isPending || dirty} title={dirty ? t("wfSaveFirst") : undefined} onClick={() => run.mutate()}>
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
            nodes={nodes}
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

/** Dify 式节点属性浮层:枚举字段用 Select,模板字段带上游变量插入器。 */
function NodeInspector({
  node,
  meta,
  graph,
  registry,
  workspaceId,
  onChange,
  onDelete,
}: {
  node: WorkflowGraph["nodes"][number];
  meta: WorkflowNodeType | null;
  graph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  workspaceId: string;
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>) => void;
  onDelete?: () => void;
}) {
  const t = useI18n();
  const config = (node.config ?? {}) as Record<string, unknown>;
  const specs = Object.entries((meta?.config ?? {}) as Record<string, ConfigSpec>);
  const fieldRefs = React.useRef<Record<string, HTMLTextAreaElement | null>>({});
  const variables = React.useMemo(
    () => upstreamVariables(graph, node.id, registry),
    [graph, node.id, registry],
  );

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

  const setConfig = (key: string, value: unknown) => onChange({ config: { ...config, [key]: value } });

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
    <aside className="wf-inspector panel">
      <div className="panel-head">
        <h2>{node.name || meta?.label || node.type}</h2>
        {onDelete && (
          <button type="button" className="inspector-delete" aria-label={t("delete")} onClick={onDelete}>
            <Trash2 size={13} />
          </button>
        )}
      </div>
      <div className="wf-inspector-body">
        <label className="wf-field">
          <span>{t("wfNodeName")}</span>
          <input value={node.name ?? ""} onChange={(event) => onChange({ name: event.target.value })} />
        </label>
        {meta && <p className="wf-node-desc">{meta.description}</p>}
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
        {specs.map(([key, spec]) => {
          const value = config[key];
          const isObject = spec?.type === "object";
          const isTemplate = spec?.type === "template" || spec?.type === "code";
          const options = spec?.options
            ? spec.options.map((option) => ({ value: option, label: option }))
            : dynamicOptions(key);
          return (
            <label className="wf-field" key={key}>
              <span>
                {key}
                {spec?.required ? " *" : ""}
              </span>
              {options ? (
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
                <textarea
                  rows={3}
                  defaultValue={JSON.stringify(value ?? {}, null, 2)}
                  onBlur={(event) => {
                    try {
                      setConfig(key, JSON.parse(event.target.value || "{}"));
                    } catch {
                      toast.error(t("wfBadJson"));
                    }
                  }}
                />
              ) : (
                <VarTextarea
                  textareaRef={(el) => {
                    fieldRefs.current[key] = el;
                  }}
                  rows={spec?.type === "code" ? 6 : spec?.type === "template" ? 2 : 1}
                  className={spec?.type === "code" ? "wf-code-input" : undefined}
                  value={String(value ?? "")}
                  onChange={(next) => setConfig(key, next)}
                  variables={variables}
                />
              )}
              {isTemplate && variables.length > 0 && (
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
