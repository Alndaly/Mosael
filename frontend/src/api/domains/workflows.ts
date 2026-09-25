import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { api } from "@/api/transport";

export type Workflow = components["schemas"]["WorkflowOut"];
export type WorkflowRevision = components["schemas"]["WorkflowRevisionOut"];
export type WorkflowRevisionDetail = components["schemas"]["WorkflowRevisionDetailOut"];
export type WorkflowNodeType = components["schemas"]["WorkflowNodeTypeOut"];
export type WorkflowTemplateId =
  | "full_video_generation"
  | "transcript_video_cleanup"
  | "translated_dub";

export interface WorkflowGraph {
  meta?: {
    template_id?: WorkflowTemplateId;
    template_version?: number;
    source?: string;
  };
  nodes: Array<{
    id: string;
    type: string;
    name?: string;
    position?: { x: number; y: number };
    config?: Record<string, unknown>;
    /** 以输入接点(连接态)暴露在节点左侧的 config 字段名。 */
    inputs?: string[];
  }>;
  /** 位置书签。**和 nodes 平级,不是一种节点** —— 它不执行、不连线,进了 nodes 就要有
   *  节点类型,而运行时会在"未知节点类型"上失败。规则见 features/markers。 */
  markers?: Array<{ id: string; name: string; x: number; y: number; shortcut?: string }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    source_handle?: string | null;
    /** 缺省 / "control" = 执行边;"data" = 数据边(带 source_output → target_input)。 */
    kind?: "control" | "data";
    source_output?: string;
    target_input?: string;
  }>;
}

export function listWorkflows(workspaceId: string): Promise<Workflow[]> {
  return api<Workflow[]>(`/api/workflows?workspace_id=${encodeURIComponent(workspaceId)}`);
}

export function createWorkflow(body: {
  workspace_id: string;
  name: string;
  description?: string;
  graph?: WorkflowGraph | null;
  template_id?: WorkflowTemplateId;
}): Promise<Workflow> {
  return api<Workflow>("/api/workflows", { method: "POST", body: JSON.stringify(body) });
}

export function getWorkflow(workflowId: string): Promise<Workflow> {
  return api<Workflow>(`/api/workflows/${workflowId}`);
}

/** 改名 / 改描述,或存整份图。**存整份图必须带底子**(读到的那份图的 graph_hash):
 *  库里那份在这期间被别处改过就撞 409,而不是把别人的写入静默盖掉。 */
export function updateWorkflow(
  workflowId: string,
  body: { name?: string; description?: string } | { graph: WorkflowGraph; base_graph_hash: string },
): Promise<Workflow> {
  return api<Workflow>(`/api/workflows/${workflowId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteWorkflow(workflowId: string): Promise<void> {
  return api<void>(`/api/workflows/${workflowId}`, { method: "DELETE" });
}

/** 导出文件信封包含文件格式版本、工作流修订与图摘要。 */
export function exportWorkflowFile(workflowId: string): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>(`/api/workflows/${workflowId}/export`);
}

export function importWorkflow(body: { workspace_id: string; data: Record<string, unknown> }): Promise<Workflow> {
  return api<Workflow>("/api/workflows/import", { method: "POST", body: JSON.stringify(body) });
}

export function runWorkflow(workflowId: string, params: Record<string, unknown> = {}): Promise<Job> {
  return api<Job>(`/api/workflows/${workflowId}/run`, { method: "POST", body: JSON.stringify({ params }) });
}

/**
 * 节点字段的动态选项(字段声明里的 `options_from`)。`parent` 是它 `depends_on` 的那个字段现在的值。
 * 所有这种字段走这一个接口 —— 前端不按节点类型写特例。
 */
/** 一个字段的动态选项。`parent` 是它依赖的那个字段的值;后两样是上下文(见后端 OptionContext)。 */
export function fetchWorkflowFieldOptions(
  source: string,
  workspaceId: string,
  parent = "",
  context: { nodeType?: string; workflowId?: string } = {},
): Promise<Array<{ value: string; label: string }>> {
  const params = new URLSearchParams({
    source,
    workspace_id: workspaceId,
    parent,
    node_type: context.nodeType ?? "",
    workflow_id: context.workflowId ?? "",
  });
  return api(`/api/workflows/field-options?${params.toString()}`);
}

export function fetchWorkflowNodeTypes(): Promise<WorkflowNodeType[]> {
  return api<WorkflowNodeType[]>("/api/workflows/node-types");
}

/** Execution history — this workflow's run jobs, newest first. */
export function listWorkflowRuns(workflowId: string): Promise<Job[]> {
  return api<Job[]>(`/api/workflows/${workflowId}/runs`);
}

/** 不可变工作流修订，最新版本在前。 */
export function listWorkflowRevisions(workflowId: string): Promise<WorkflowRevision[]> {
  return api<WorkflowRevision[]>(`/api/workflows/${workflowId}/revisions`);
}

export function getWorkflowRevision(workflowId: string, revision: number): Promise<WorkflowRevisionDetail> {
  return api<WorkflowRevisionDetail>(`/api/workflows/${workflowId}/revisions/${revision}`);
}

/** 恢复会追加一个新修订，不会覆盖目标或当前历史。 */
export function restoreWorkflowRevision(workflowId: string, revision: number): Promise<Workflow> {
  return api<Workflow>(`/api/workflows/${workflowId}/revisions/${revision}/restore`, { method: "POST" });
}

/**
 * 「认可这一版」:不改图、不增版,只把自己记成这一版的担保人。同事改过的一版要借你的私有账号 /
 * 档案 / 本机文件时,运行会停下来要你认可(见后端 domain/authority)。
 */
export function attestWorkflowRevision(workflowId: string, revision: number): Promise<WorkflowRevision> {
  return api<WorkflowRevision>(`/api/workflows/${workflowId}/revisions/${revision}/attest`, { method: "POST" });
}

/** 运行失败现场里的「哪条工作流的哪一版等人认可」。 */
export type RevisionAttestRequest = { workflow_id: string; workflow_name: string; revision: number };

export function attestRequestOf(value: unknown): RevisionAttestRequest | null {
  if (!value || typeof value !== "object") return null;
  const one = value as Record<string, unknown>;
  const revision = Number(one.revision);
  if (typeof one.workflow_id !== "string" || !one.workflow_id || !Number.isFinite(revision) || revision <= 0) return null;
  return { workflow_id: one.workflow_id, workflow_name: String(one.workflow_name ?? ""), revision };
}

/** 官方模板目录:名字、介绍、步骤、前置条件。文案由后端按语言选好(图标在前端)。 */
export type WorkflowTemplate = components["schemas"]["WorkflowTemplateOut"];
export function fetchWorkflowTemplates(): Promise<WorkflowTemplate[]> {
  return api<WorkflowTemplate[]>("/api/workflows/templates");
}
