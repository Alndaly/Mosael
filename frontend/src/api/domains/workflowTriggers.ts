/**
 * 工作流触发器(ADR 0065)的接口。
 *
 * **路径只写在这里**(见 design/apiSeam.test.ts):界面里现拼 `/api/…` 的代价是改一个接口要满仓库
 * 找字符串、拼错只在运行时变成 404,而返回值没有类型把关。
 *
 * 两份类型是**手写**的:生成物 `api/generated/schema.d.ts` 要 `pnpm gen:api` 从
 * `backend/openapi.json` 重导才有这一族,而这一笔不动那两份生成物(会和另一笔在途的改动撞车)。
 * 后端 `routes/triggers.py` 里那两张 out schema 就是这两份的形状 —— **重导之后换成
 * `components["schemas"]["WorkflowTriggerOut"]` / `["WorkflowTriggerEventOut"]` 即可**,
 * 字段一个不多一个不少(见报告)。
 */

import { api } from "@/api/transport";

export type WorkflowTrigger = {
  id: string;
  workspace_id: string;
  workflow_id: string;
  name: string;
  /** 空 = 这个工作区里任意机器人。 */
  bot_id: string;
  /** 空 = 这个机器人所在的任意会话。 */
  chat_id: string;
  /** text(含富文本)/ image / file / media。 */
  message_types: string[];
  keywords: string[];
  only_from_open_ids: string[];
  /** 开始节点参数名 → 含 trigger 占位符的模板。 */
  params: Record<string, string>;
  reply_in_chat: boolean;
  max_runs_per_minute: number;
  enabled: boolean;
  last_fired_at: string | null;
  created_at: string;
};

export type WorkflowTriggerEvent = {
  id: string;
  message_id: string;
  message_type: string;
  text_preview: string;
  asset_ids: string[];
  job_id: string | null;
  /** started / throttled / refused / failed / skipped */
  status: string;
  error: string;
  created_at: string;
};

export type WorkflowTriggerInput = {
  workspace_id: string;
  workflow_id: string;
  name: string;
  bot_id: string;
  chat_id: string;
  message_types: string[];
  keywords: string[];
  params: Record<string, string>;
  reply_in_chat: boolean;
  max_runs_per_minute: number;
};

/** 改一条触发器时要送的那几格(工作区和绑的工作流是创建时定的,改绑走 workflow_id)。 */
export type WorkflowTriggerChanges = Partial<Omit<WorkflowTriggerInput, "workspace_id">> & { enabled?: boolean };

const BASE = "/api/workflow-triggers";

export function listWorkflowTriggers(workspaceId: string, workflowId: string): Promise<WorkflowTrigger[]> {
  return api<WorkflowTrigger[]>(
    `${BASE}?workspace_id=${encodeURIComponent(workspaceId)}&workflow_id=${encodeURIComponent(workflowId)}`,
  );
}

export function createWorkflowTrigger(body: WorkflowTriggerInput): Promise<WorkflowTrigger> {
  return api<WorkflowTrigger>(BASE, { method: "POST", body: JSON.stringify(body) });
}

export function updateWorkflowTrigger(
  triggerId: string,
  changes: WorkflowTriggerChanges,
): Promise<WorkflowTrigger> {
  return api<WorkflowTrigger>(`${BASE}/${encodeURIComponent(triggerId)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function deleteWorkflowTrigger(triggerId: string): Promise<void> {
  return api<void>(`${BASE}/${encodeURIComponent(triggerId)}`, { method: "DELETE" });
}

export function listWorkflowTriggerEvents(triggerId: string, limit = 20): Promise<WorkflowTriggerEvent[]> {
  return api<WorkflowTriggerEvent[]>(`${BASE}/${encodeURIComponent(triggerId)}/events?limit=${limit}`);
}
