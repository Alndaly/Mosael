import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { api } from "@/api/transport";

export type Workflow = components["schemas"]["WorkflowOut"];
export type WorkflowNodeType = components["schemas"]["WorkflowNodeTypeOut"];

export interface WorkflowGraph {
  nodes: Array<{
    id: string;
    type: string;
    name?: string;
    position?: { x: number; y: number };
    config?: Record<string, unknown>;
    /** 以输入接点(连接态)暴露在节点左侧的 config 字段名。 */
    inputs?: string[];
  }>;
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
  template_id?: "full_video_generation";
}): Promise<Workflow> {
  return api<Workflow>("/api/workflows", { method: "POST", body: JSON.stringify(body) });
}

export function updateWorkflow(
  workflowId: string,
  body: { name?: string; description?: string; graph?: WorkflowGraph },
): Promise<Workflow> {
  return api<Workflow>(`/api/workflows/${workflowId}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function deleteWorkflow(workflowId: string): Promise<void> {
  return api<void>(`/api/workflows/${workflowId}`, { method: "DELETE" });
}

/** 导出文件信封:{format, version, name, description, graph}。 */
export function exportWorkflowFile(workflowId: string): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>(`/api/workflows/${workflowId}/export`);
}

export function importWorkflow(body: { workspace_id: string; data: Record<string, unknown> }): Promise<Workflow> {
  return api<Workflow>("/api/workflows/import", { method: "POST", body: JSON.stringify(body) });
}

export function runWorkflow(workflowId: string, params: Record<string, unknown> = {}): Promise<Job> {
  return api<Job>(`/api/workflows/${workflowId}/run`, { method: "POST", body: JSON.stringify({ params }) });
}

export function fetchWorkflowNodeTypes(): Promise<WorkflowNodeType[]> {
  return api<WorkflowNodeType[]>("/api/workflows/node-types");
}

/** Execution history — this workflow's run jobs, newest first. */
export function listWorkflowRuns(workflowId: string): Promise<Job[]> {
  return api<Job[]>(`/api/workflows/${workflowId}/runs`);
}
