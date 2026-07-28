/**
 * Open Studio tools as pi AgentTools — generated entirely from the backend registry.
 *
 * pi has no MCP, so tools come from GET /api/agent/tools (the manifest derived from
 * mcp_server.py, the single tool registry) and execute via POST /api/agent/tools/{name}.
 * There is no hand-written second list any more: the seven tools that used to live here in
 * source (read-only trio + confirmation-gated quartet) drifted from the registry once and
 * silently cost the agent nineteen tools — see backend/app/api/routes/agent_tools.py.
 *
 * Confirmation-gated tools are not special-cased by name: the manifest marks them with
 * `confirmation: true`, and any such tool gets the same generic wrapper — invoke (creates the
 * pending card), then block-poll /api/confirmations/{id} until the user resolves it, so the
 * model receives the executed result rather than a pending stub.
 */
import type { AgentTool, AgentToolResult } from "@earendil-works/pi-agent-core";

import { log } from "./protocol.js";

async function apiGet(
  apiBase: string,
  token: string,
  path: string,
  params?: Record<string, string | number>,
): Promise<unknown> {
  const url = new URL(apiBase + path);
  if (params) for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res.json();
}

async function apiPost(apiBase: string, token: string, path: string, body: unknown): Promise<unknown> {
  const res = await fetch(apiBase + path, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} -> ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res.json();
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(id); reject(new Error("aborted")); }, { once: true });
  });
}

interface Confirmation { id: string; status: string; result: unknown; error?: string | null }

/**
 * Block until the user resolves a confirmation card in Open Studio.
 * pending -> approved -> executed(result) | failed(error) | rejected. This is the
 * confirmation gate: the agent's turn waits here until the user acts.
 */
async function awaitConfirmation(
  apiBase: string,
  token: string,
  confirmationId: string,
  signal: AbortSignal | undefined,
): Promise<unknown> {
  // 人工批准是人速的,轮询上限给足(后端 turn 超时 600s 兜底)
  for (let waited = 0; waited < 590_000; waited += 1500) {
    const cur = (await apiGet(apiBase, token, `/api/confirmations/${confirmationId}`)) as Confirmation;
    if (cur.status === "executed") return cur.result;
    if (cur.status === "rejected") throw new Error("用户拒绝了该操作");
    if (cur.status === "failed") throw new Error(`执行失败:${cur.error ?? "unknown"}`);
    await sleep(1500, signal);
  }
  throw new Error("等待用户确认超时");
}

/**
 * A tool result the model can read AND the UI can render.
 *
 * `content` is what the model sees, so it stays text. `details` carries the same value with
 * its structure intact — without it the UI receives a JSON string and has nothing to render
 * but the string, which is why every tool result used to appear as a wall of escaped JSON.
 */
function jsonResult(data: unknown): AgentToolResult<{ data: unknown }> {
  return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], details: { data } };
}

interface ToolSpec {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  confirmation?: boolean;
}

/** 展示用中文标签(纯 UI;没有条目的工具直接显示 name)。 */
const TOOL_LABELS: Record<string, string> = {
  list_projects: "列出项目",
  list_assets: "列出素材",
  inspect_sequence: "查看时间线",
  edit_timeline: "修改时间线",
  render_sequence: "导出时间线",
  generate_image: "生成图片",
  generate_video: "生成视频",
  create_workflow: "新建工作流",
  edit_workflow: "编辑工作流",
  update_workflow: "更新工作流",
  run_workflow: "运行工作流",
};

/** All Open Studio tools for a turn, generated from the backend manifest. */
export async function buildAllTools(apiBase: string, token: string, workspaceId: string): Promise<AgentTool[]> {
  let specs: ToolSpec[];
  try {
    specs = (await apiGet(apiBase, token, "/api/agent/tools")) as ToolSpec[];
  } catch (err) {
    // 没有 manifest 就没有工具面;宁可空手起 turn(模型会说明情况),也不要一份注定漂移的内置副本。
    log("could not load the tool manifest; starting the turn without tools:", String(err));
    return [];
  }

  return specs
    .filter((spec) => spec?.name)
    .map((spec) => {
      const properties = (spec.parameters?.properties ?? {}) as Record<string, unknown>;
      const takesWorkspace = "workspace_id" in properties;
      return {
        name: spec.name,
        label: TOOL_LABELS[spec.name] ?? spec.name,
        description: spec.description || spec.name,
        // The manifest's parameters are already JSON Schema, which is what pi wants.
        parameters: (spec.parameters ?? { type: "object", properties: {} }) as never,
        execute: async (_id: string, rawParams: unknown, signal?: AbortSignal) => {
          const args = { ...((rawParams ?? {}) as Record<string, unknown>) };
          // Fill in the workspace only for tools that declare it: the model has no reason to
          // know which workspace this turn belongs to, but the tools are plain Python functions
          // and an argument they do not accept is a TypeError, not an ignored extra. Injecting
          // it blindly broke every tool without the parameter — web_search, analyze_asset —
          // on the first call.
          if (workspaceId && !args.workspace_id && takesWorkspace) args.workspace_id = workspaceId;
          const response = (await apiPost(apiBase, token, `/api/agent/tools/${spec.name}`, {
            arguments: args,
            requested_by: "pi-agent",
          })) as { result?: unknown; error?: string };
          if (response?.error) throw new Error(response.error);
          if (!spec.confirmation) return jsonResult(response?.result ?? null);
          // 确认门控:调用只创建了待确认卡,阻塞等用户在 Open Studio 里批准后把执行结果给模型。
          const card = (response?.result ?? {}) as { confirmation_id?: string };
          if (!card.confirmation_id) throw new Error("确认卡创建失败(缺 confirmation_id)");
          return jsonResult(await awaitConfirmation(apiBase, token, card.confirmation_id, signal));
        },
      };
    });
}
