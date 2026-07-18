/**
 * Mibu tools as pi AgentTools (S3: read-only set).
 *
 * pi has no MCP, so instead of Mibu's mcp_server.py we register native pi
 * tools whose implementation calls Mibu's REST API directly (bearer token
 * from the turn). This slice covers read-only tools — no confirmation cards.
 * Mutation tools (edit_timeline / render / generate) + the confirmation-wait
 * gate come in S4.
 */
import { Type } from "@earendil-works/pi-ai";
import type { AgentTool, AgentToolResult } from "@earendil-works/pi-agent-core";

async function mibuGet(
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

async function mibuPost(apiBase: string, token: string, path: string, body: unknown): Promise<unknown> {
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
 * Create a confirmation card and block until the user resolves it in Mibu.
 * pending -> approved -> executed(result) | failed(error) | rejected. This is
 * the confirmation gate: the agent's turn waits here until the user acts.
 */
async function createAndAwaitConfirmation(
  apiBase: string,
  token: string,
  workspaceId: string,
  tool: string,
  payload: unknown,
  signal: AbortSignal | undefined,
): Promise<unknown> {
  const card = (await mibuPost(apiBase, token, "/api/confirmations", {
    workspace_id: workspaceId,
    tool,
    requested_by: "pi-agent",
    payload,
  })) as Confirmation;
  // 人工批准是人速的,轮询上限给足(后端 turn 超时 600s 兜底)
  for (let waited = 0; waited < 590_000; waited += 1500) {
    const cur = (await mibuGet(apiBase, token, `/api/confirmations/${card.id}`)) as Confirmation;
    if (cur.status === "executed") return cur.result;
    if (cur.status === "rejected") throw new Error("用户拒绝了该操作");
    if (cur.status === "failed") throw new Error(`执行失败:${cur.error ?? "unknown"}`);
    await sleep(1500, signal);
  }
  throw new Error("等待用户确认超时");
}

function jsonResult(data: unknown): AgentToolResult<Record<string, never>> {
  return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], details: {} };
}

/** Read-only tools bound to a single turn's workspace + credentials. */
export function buildReadonlyTools(apiBase: string, token: string, workspaceId: string): AgentTool[] {
  const tools: AgentTool[] = [
    {
      name: "list_projects",
      label: "列出项目",
      description: "列出当前工作区的项目及其 active_sequence_id。",
      parameters: Type.Object({}),
      execute: async () =>
        jsonResult(await mibuGet(apiBase, token, "/api/projects", { workspace_id: workspaceId })),
    },
    {
      name: "list_assets",
      label: "列出素材",
      description: "列出当前工作区的素材(图片 / 视频 / 音频)及基本信息。",
      parameters: Type.Object({}),
      execute: async () =>
        jsonResult(await mibuGet(apiBase, token, "/api/assets", { workspace_id: workspaceId })),
    },
    {
      name: "inspect_sequence",
      label: "查看时间线",
      description:
        "查看一个序列(时间线)的轨道与片段。传 sequence_id;若只有 project_id,会取该项目的第一个序列。",
      parameters: Type.Object({
        sequence_id: Type.Optional(Type.String({ description: "序列 ID" })),
        project_id: Type.Optional(Type.String({ description: "项目 ID(用其激活/首个序列)" })),
      }),
      // pi 已按 parameters schema 校验过实参,这里只是给 TS 一个具体形状
      execute: async (_id, rawParams) => {
        const params = rawParams as { sequence_id?: string; project_id?: string };
        let sequenceId = params.sequence_id;
        if (!sequenceId && params.project_id) {
          const seqs = (await mibuGet(apiBase, token, `/api/projects/${params.project_id}/sequences`)) as Array<{ id: string }>;
          sequenceId = seqs?.[0]?.id;
        }
        if (!sequenceId) throw new Error("需要 sequence_id 或 project_id");
        return jsonResult(await mibuGet(apiBase, token, `/api/sequences/${sequenceId}`));
      },
    },
  ];
  return tools;
}

/**
 * Mutation tools (S4). Each proposes a confirmation card and blocks until the
 * user approves in Mibu; the executed result is returned to the model. The
 * confirmation kernel + REST are unchanged — only the caller is now a pi tool.
 */
export function buildMutationTools(apiBase: string, token: string, workspaceId: string): AgentTool[] {
  const propose = (tool: string, payload: unknown, signal?: AbortSignal) =>
    createAndAwaitConfirmation(apiBase, token, workspaceId, tool, payload, signal);
  const tools: AgentTool[] = [
    {
      name: "edit_timeline",
      label: "修改时间线",
      description:
        "提出时间线修改(需用户确认后执行,可撤销)。operations 是操作数组,每项 {kind, ...}:" +
        "insert_clip / move_clip / trim_clip / delete_clip / cut_clip_range / add_track / remove_track / set_clip_effects。",
      parameters: Type.Object({
        sequence_id: Type.String({ description: "目标序列 ID" }),
        operations: Type.Array(Type.Object({ kind: Type.String() }, { additionalProperties: true }), {
          description: "操作列表,每项含 kind 及其参数",
        }),
      }),
      execute: async (_id, rawParams, signal) => {
        const p = rawParams as { sequence_id: string; operations: unknown[] };
        return jsonResult(await propose("edit_timeline", { sequence_id: p.sequence_id, operations: p.operations }, signal));
      },
    },
    {
      name: "render_sequence",
      label: "导出时间线",
      description: "导出一个序列为 mp4(有渲染成本,需用户确认)。批准后返回渲染任务信息。",
      parameters: Type.Object({ sequence_id: Type.String({ description: "要导出的序列 ID" }) }),
      execute: async (_id, rawParams, signal) => {
        const p = rawParams as { sequence_id: string };
        return jsonResult(await propose("render_sequence", { sequence_id: p.sequence_id }, signal));
      },
    },
    {
      name: "generate_image",
      label: "生成图片",
      description: "根据提示词生成图片素材(有 AI 成本,需用户确认)。批准后素材落入素材池。",
      parameters: Type.Object({
        prompt: Type.String({ description: "图片描述" }),
        model: Type.Optional(Type.String()),
        provider: Type.Optional(Type.String()),
      }),
      execute: async (_id, rawParams, signal) => {
        const p = rawParams as { prompt: string; model?: string; provider?: string };
        return jsonResult(
          await propose(
            "generate_image",
            { prompt: p.prompt, provider: p.provider || "mock", model: p.model || "mock-image", parameters: {} },
            signal,
          ),
        );
      },
    },
    {
      name: "generate_video",
      label: "生成视频",
      description: "根据提示词生成视频素材(有 AI 成本,需用户确认)。",
      parameters: Type.Object({
        prompt: Type.String({ description: "视频描述" }),
        model: Type.Optional(Type.String()),
        provider: Type.Optional(Type.String()),
      }),
      execute: async (_id, rawParams, signal) => {
        const p = rawParams as { prompt: string; model?: string; provider?: string };
        return jsonResult(
          await propose(
            "generate_video",
            { prompt: p.prompt, provider: p.provider || "mock", model: p.model || "mock-video", parameters: {} },
            signal,
          ),
        );
      },
    },
  ];
  return tools;
}

/** All Mibu tools available to a turn: read-only + mutation (confirmation-gated). */
export function buildAllTools(apiBase: string, token: string, workspaceId: string): AgentTool[] {
  return [...buildReadonlyTools(apiBase, token, workspaceId), ...buildMutationTools(apiBase, token, workspaceId)];
}
