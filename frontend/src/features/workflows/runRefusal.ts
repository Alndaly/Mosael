import { ApiError } from "@/api/client";
import { failureFields, type FailureFix } from "@/components/failure/FailureCard";
import type { ScopePath } from "@/features/workflows/scope";

/**
 * 点运行被服务端拦下的那一次(开跑前的检查:缺必填、引用指不到、插件连接落不到……)。
 *
 * 后端回 422 `{code: "workflow_run_refused", message, error_summary, error_detail, error_hint, scope, node_id, field}`
 * (routes/workflows `_run_refused`)。此前编辑器只弹一下 toast:「有多个连接,请选一个」几秒就没了,没说是哪个节点、
 * 也没说去哪选 —— 选连接的那一格在「高级」里。现在编辑器把它摆成和跑失败同一张失败卡,带一颗「去这个节点」。
 */
export type RunRefusal = {
  summary: string;
  detail: string | null;
  fix: FailureFix | null;
  copyText: string;
  /** 拦在哪一层(容器节点 id 一串;顶层是空的)、哪个节点、哪一格。整条流程的问题没有节点。 */
  scope: ScopePath;
  nodeId: string | null;
  field: string | null;
};

type RefusalBody = {
  code?: unknown;
  message?: unknown;
  error_summary?: string | null;
  error_detail?: string | null;
  error_hint?: FailureFix | null;
  scope?: unknown;
  node_id?: unknown;
  field?: unknown;
};

/** 这次失败是不是「开跑前被拦下」;别的失败(断网、500……)返回 null,照旧走 toast。 */
export function runRefusalOf(error: unknown): RunRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  let detail: RefusalBody;
  try {
    detail = (JSON.parse(error.body) as { detail?: RefusalBody }).detail ?? {};
  } catch {
    return null;
  }
  if (detail.code !== "workflow_run_refused") return null;
  const message = typeof detail.message === "string" ? detail.message : error.message;
  return {
    ...failureFields({ ...detail, error: message }, error.message),
    scope: Array.isArray(detail.scope) ? detail.scope.map(String) : [],
    nodeId: typeof detail.node_id === "string" && detail.node_id ? detail.node_id : null,
    field: typeof detail.field === "string" && detail.field ? detail.field : null,
  };
}
