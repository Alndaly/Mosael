import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  Handle,
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
  BookOpen,
  Loader2,
  Mic,
  Play,
  Plus,
  Save,
  Sparkles,
  Trash2,
  Wand2,
  Workflow as WorkflowIcon,
  Wrench,
  Download,
  Flag,
  Type,
} from "lucide-react";
import { toast } from "sonner";

import {
  aiEditWorkflow,
  createWorkflow,
  deleteWorkflow,
  fetchWorkflowNodeTypes,
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
import { ConfirmDialog, RenameDialog } from "@/components/ui/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

/** 节点类型 → 图标(与节点面板/画布一致)。 */
const NODE_ICONS: Record<string, React.ReactNode> = {
  start: <Flag size={13} />,
  llm: <Sparkles size={13} />,
  kb_search: <BookOpen size={13} />,
  plugin_tool: <Wrench size={13} />,
  transcribe_asset: <Mic size={13} />,
  export_sequence: <Download size={13} />,
  ai_generate: <Wand2 size={13} />,
};

interface WfNodeData extends Record<string, unknown> {
  label: string;
  nodeType: string;
  typeLabel: string;
}

/** 画布节点:图标 + 名称 + 类型标签,全平面卡片。 */
function WfNode({ data, selected }: NodeProps) {
  const d = data as WfNodeData;
  return (
    <div className={selected ? "wf-node selected" : "wf-node"}>
      {d.nodeType !== "start" && <Handle type="target" position={Position.Left} className="wf-handle" />}
      <span className={`wf-node-icon wf-icon-${d.nodeType}`}>{NODE_ICONS[d.nodeType] ?? <Type size={13} />}</span>
      <span className="wf-node-text">
        <strong>{d.label}</strong>
        <small>{d.typeLabel}</small>
      </span>
      <Handle type="source" position={Position.Right} className="wf-handle" />
    </div>
  );
}

const NODE_COMPONENT_TYPES = { wf: WfNode };

export function WorkflowsView({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const workflows = useQuery({
    queryKey: ["workflows", workspace.id],
    queryFn: () => listWorkflows(workspace.id),
  });
  const nodeTypes = useQuery({ queryKey: ["workflow-node-types"], queryFn: fetchWorkflowNodeTypes, staleTime: Infinity });

  const create = useMutation({
    mutationFn: () => createWorkflow({ workspace_id: workspace.id, name: t("wfDefaultName"), description: "" }),
    onSuccess: (workflow) => {
      setSelectedId(workflow.id);
      void qc.invalidateQueries({ queryKey: ["workflows", workspace.id] });
    },
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
              <button
                key={workflow.id}
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
  return (graph.edges ?? []).map((edge) => ({ id: edge.id, source: edge.source, target: edge.target }));
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
  const [aiOpen, setAiOpen] = React.useState(false);
  const [aiInstruction, setAiInstruction] = React.useState("");

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

  const onConnect = React.useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) return;
    const id = `e-${connection.source}-${connection.target}`;
    setEdges((current) =>
      current.some((edge) => edge.id === id) ? current : [...current, { id, source: connection.source!, target: connection.target! }],
    );
    setGraph((current) =>
      current.edges.some((edge) => edge.id === id)
        ? current
        : { ...current, edges: [...current.edges, { id, source: connection.source!, target: connection.target! }] },
    );
    setDirty(true);
  }, []);

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
  const aiEdit = useMutation({
    mutationFn: () => aiEditWorkflow(workflow.id, { instruction: aiInstruction, graph }),
    onSuccess: (response) => {
      applyGraph(response.graph as unknown as WorkflowGraph);
      setAiOpen(false);
      setAiInstruction("");
      toast.success(t("wfAiApplied"), { description: response.summary || undefined });
    },
    onError: (error: Error) => toast.error(t("wfAiFailed"), { description: error.message }),
  });

  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null;

  return (
    <div className="wf-editor">
      <div className="wf-toolbar">
        <button type="button" className="wf-title" onClick={() => setRenaming(true)} title={t("rename")}>
          <WorkflowIcon size={14} />
          <strong>{workflow.name}</strong>
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
          <Popover open={aiOpen} onOpenChange={setAiOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm">
                <Sparkles size={13} /> {t("wfAiEdit")}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="wf-ai-pop" align="end">
              <strong>{t("wfAiEdit")}</strong>
              <textarea
                rows={3}
                value={aiInstruction}
                placeholder={t("wfAiPlaceholder")}
                onChange={(event) => setAiInstruction(event.target.value)}
              />
              <div className="wf-ai-actions">
                <Button
                  size="sm"
                  disabled={!aiInstruction.trim() || aiEdit.isPending}
                  onClick={() => aiEdit.mutate()}
                >
                  {aiEdit.isPending ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />} {t("wfAiApply")}
                </Button>
              </div>
            </PopoverContent>
          </Popover>
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
            onNodeClick={(_event, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            fitView
            proOptions={{ hideAttribution: false }}
            deleteKeyCode={["Backspace", "Delete"]}
          >
            <Background gap={18} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        {selectedNode && (
          <NodeInspector
            node={selectedNode}
            meta={registry.get(selectedNode.type) ?? null}
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

/** 右侧节点属性面板:按注册表渲染 config 字段。 */
function NodeInspector({
  node,
  meta,
  onChange,
  onDelete,
}: {
  node: WorkflowGraph["nodes"][number];
  meta: WorkflowNodeType | null;
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>) => void;
  onDelete?: () => void;
}) {
  const t = useI18n();
  const config = (node.config ?? {}) as Record<string, unknown>;
  const specs = Object.entries((meta?.config ?? {}) as Record<string, { type?: string; description?: string; required?: boolean }>);

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
        {specs.map(([key, spec]) => {
          const value = config[key];
          const isObject = spec?.type === "object";
          return (
            <label className="wf-field" key={key}>
              <span>
                {key}
                {spec?.required ? " *" : ""}
              </span>
              {isObject ? (
                <textarea
                  rows={3}
                  defaultValue={JSON.stringify(value ?? {}, null, 2)}
                  onBlur={(event) => {
                    try {
                      onChange({ config: { ...config, [key]: JSON.parse(event.target.value || "{}") } });
                    } catch {
                      toast.error(t("wfBadJson"));
                    }
                  }}
                />
              ) : (
                <textarea
                  rows={spec?.type === "template" ? 2 : 1}
                  value={String(value ?? "")}
                  onChange={(event) => onChange({ config: { ...config, [key]: event.target.value } })}
                />
              )}
              {spec?.description && <small>{spec.description}</small>}
            </label>
          );
        })}
        {meta && (
          <p className="wf-node-outputs">
            {t("wfOutputs")}: {meta.outputs.map((output) => `{{${node.id}.${output}}}`).join("  ")}
          </p>
        )}
      </div>
    </aside>
  );
}
