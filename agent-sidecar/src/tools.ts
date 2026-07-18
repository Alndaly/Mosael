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
