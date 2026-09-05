/**
 * Mosael tools as pi AgentTools — generated entirely from the backend registry.
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

/**
 * 一次调用等后端的时限。
 *
 * 不设的话生效的是 undici 的默认 headersTimeout(300s),而它抛出来的是一句 `fetch failed`。
 * 真机上模型读到这句话得出的结论是「可能是临时网络问题,我重试一次」—— 然后第二次撞进同一
 * 堵墙。后端就在回环地址上,这里几乎不可能是网络;把这一点说清楚,重试才不会被当成办法。
 *
 * 180s 的来历:最长的**合法**单次调用是 sleep(封顶 60s,见 mcp_server.SLEEP_CAP_SECONDS),
 * 浏览器等待默认 15s。留足余量,同时**必须低于** undici 的 300s —— 要由我们先超时,否则抛
 * 出来的还是那句没有信息的 fetch failed。
 */
const TOOL_CALL_TIMEOUT_MS = 180_000;

/** 把这一轮的取消信号和调用时限合成一个:停止这一轮时,在飞的 HTTP 也要真的断掉。 */
function deadline(signal: AbortSignal | undefined, ms: number): AbortSignal {
  const limit = AbortSignal.timeout(ms);
  return signal ? AbortSignal.any([signal, limit]) : limit;
}

/**
 * 发一次请求,并且**把失败说清楚**。
 *
 * `fetch failed` 是 undici 把一切传输层问题压成的一句话:超时、连接被拒、进程没了,读起来
 * 完全一样。模型拿它没有任何可依据的下一步,于是只会重试。这里把三件事分开说。
 */
async function request(
  url: string | URL,
  init: RequestInit,
  what: string,
  ms: number,
  signal?: AbortSignal,
): Promise<Response> {
  const started = Date.now();
  try {
    return await fetch(url, { ...init, signal: deadline(signal, ms) });
  } catch (error) {
    const waited = Math.round((Date.now() - started) / 1000);
    if (signal?.aborted) throw new Error(`${what} 已取消(这一轮被停止)`);
    const reason = (error as { name?: string })?.name;
    if (reason === "TimeoutError" || reason === "AbortError") {
      throw new Error(
        `${what}:本机后端 ${waited}s 没有响应。它跑在回环地址上,这不是网络问题 —— ` +
          "重试大概率还是同一个结果。先做别的,或者让用户看一眼后端日志。",
      );
    }
    throw new Error(`${what}:连不上本机后端(${waited}s 后 ${String(error)})—— 它可能已经退出了。`);
  }
}

async function apiGet(
  apiBase: string,
  token: string,
  path: string,
  params?: Record<string, string | number>,
  signal?: AbortSignal,
): Promise<unknown> {
  const url = new URL(apiBase + path);
  if (params) for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
  const res = await request(url, { headers: { Authorization: `Bearer ${token}` } }, `GET ${path}`, TOOL_CALL_TIMEOUT_MS, signal);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return res.json();
}

async function apiPost(
  apiBase: string,
  token: string,
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<unknown> {
  const res = await request(
    apiBase + path,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    `POST ${path}`,
    TOOL_CALL_TIMEOUT_MS,
    signal,
  );
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
 * Block until the user resolves a confirmation card in Mosael.
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
    const cur = (await apiGet(apiBase, token, `/api/confirmations/${confirmationId}`, undefined, signal)) as Confirmation;
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
  read_only?: boolean;
}

/** 展示用中文标签(纯 UI;没有条目的工具直接显示 name)。 */
const TOOL_LABELS: Record<string, string> = {
  list_projects: "列出项目",
  list_assets: "列出素材",
  inspect_sequence: "查看时间线",
  edit_timeline: "修改时间线",
  render_sequence: "导出时间线",
  convert_video_to_gif: "视频转 GIF",
  generate_image: "生成图片",
  generate_video: "生成视频",
  create_workflow: "新建工作流",
  edit_workflow: "编辑工作流",
  update_workflow: "更新工作流",
  run_workflow: "运行工作流",
  list_agent_sessions: "查看智能体会话",
  notify_agent_session: "通知另一个智能体",
};

/** All Mosael tools for a turn, generated from the backend manifest. */
export async function buildAllTools(
  apiBase: string,
  token: string,
  workspaceId: string,
): Promise<AgentTool[]> {
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
        confirmation: Boolean(spec.confirmation),
        // 子智能体只拿只读工具,判据就是这个标记 —— 名单在后端(唯一工具注册表),
        // 这边再抄一份名字清单必然漂移(那种漂移让十九个工具静默消失过一次)。
        // 内置工具的只读 = 没有确认门;插件工具要 manifest 明写,默认不算。
        readOnly: Boolean(spec.read_only),
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
            // **不再转述 sessionId**:这次调用属于哪次对话,后端从 token 认出来(turn 令牌铸造时
            // 就带着它)。转述的东西可以被伪造,而确认卡的归属决定它出现在谁面前、以后还决定
            // 要不要自动放行。
          }, signal)) as { result?: unknown; error?: string };
          if (response?.error) throw new Error(response.error);
          if (!spec.confirmation) return jsonResult(response?.result ?? null);
          // 确认门控:调用只创建了待确认卡,阻塞等用户在 Mosael 里批准后把执行结果给模型。
          const card = (response?.result ?? {}) as { confirmation_id?: string };
          if (!card.confirmation_id) throw new Error("确认卡创建失败(缺 confirmation_id)");
          return jsonResult(await awaitConfirmation(apiBase, token, card.confirmation_id, signal));
        },
      };
    });
}
