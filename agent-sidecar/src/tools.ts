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
 *
 * `awaits_answer: true` (ask_user) is the same shape pointed at the question card, with one
 * difference that matters: a confirmation that times out means the action never happened, so
 * that one throws; a question that times out only means the user has not got to it yet — the
 * answer still reaches the conversation later — so that one returns "pending" and lets the
 * model carry on instead of reporting a failure and asking all over again.
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

/**
 * 一张确认卡最多等多久。
 *
 * **压在后端 TURN_TIMEOUT_SECONDS(600s)底下** —— 超过它,卡还亮着而那一轮已经被判超时,
 * 用户点批准之后什么都不会发生。这条关系此前只写在这里的注释里,而**改 Python 那个 600 的人
 * 没有任何理由来读一段 TypeScript 注释**。现在它由 contracts/shared-constants.json 的
 * budgets 钉着(提成具名常量,就是为了让那条契约读得到它)。
 */
const CARD_WAIT_CEILING_MS = 590_000;

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
interface Question { id: string; status: string; answers: unknown }

/**
 * 等用户在 Mosael 里处理掉一张卡 —— 这次 turn 就停在这里。
 *
 * 人工操作是人速的,所以上限给足:590s,压在后端 TURN_TIMEOUT_SECONDS(600s)底下 ——
 * 要由我们先到点,不然模型收到的是一句没有信息的「智能体运行超过 600 秒」。
 * 环境变量只为**测得到超时那一支**存在:不给这个口子的话,验证"到点之后给的是什么"
 * 得让测试原地坐十分钟,于是那一支永远没人验。
 *
 * `settle` 返回 undefined 表示还没定下来,继续等;抛错就是终局的坏结果。到点之后由调用方
 * 决定是抛错还是给一个"还没轮到"的回包 —— 那正是确认卡和选择卡唯一不同的地方。
 */
async function awaitCard<T>(
  read: () => Promise<T>,
  settle: (current: T) => unknown | undefined,
  signal: AbortSignal | undefined,
): Promise<unknown | undefined> {
  const ceiling = Number(process.env.MOSAEL_CARD_WAIT_MS) || CARD_WAIT_CEILING_MS;
  const step = Math.min(1500, ceiling);
  for (let waited = 0; waited < ceiling; waited += step) {
    const settled = settle(await read());
    if (settled !== undefined) return settled;
    await sleep(step, signal);
  }
  return undefined;
}

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
  const settled = await awaitCard<Confirmation>(
    () => apiGet(apiBase, token, `/api/confirmations/${confirmationId}`, undefined, signal) as Promise<Confirmation>,
    (cur) => {
      if (cur.status === "executed") return { result: cur.result };
      if (cur.status === "rejected") throw new Error("用户拒绝了该操作");
      if (cur.status === "failed") throw new Error(`执行失败:${cur.error ?? "unknown"}`);
      return undefined;
    },
    signal,
  );
  // 超时 = 这个动作**没有发生**。说成别的都会让模型以为它做过了。
  if (settled === undefined) throw new Error("等待用户确认超时");
  return (settled as { result: unknown }).result;
}

/**
 * Block until the user answers (or skips) a question card in Mosael.
 *
 * 到点不抛错:超时只说明用户还没顾上,而答案**仍然会到** —— 作答后由回执送回这次对话
 * (backend domain/agent/questions.deliver_to_session,插进当时那一轮)。抛错会让模型以为
 * 「问这件事失败了」,转头把同一张卡再立一遍,而第一张还在用户面前。
 */
async function awaitAnswer(
  apiBase: string,
  token: string,
  questionId: string,
  signal: AbortSignal | undefined,
): Promise<unknown> {
  const settled = await awaitCard<Question>(
    () => apiGet(apiBase, token, `/api/agent/questions/${questionId}`, undefined, signal) as Promise<Question>,
    (cur) => {
      if (cur.status === "answered") return { status: "answered", answers: cur.answers ?? {} };
      if (cur.status === "dismissed") return { status: "dismissed", skipped: true };
      return undefined;
    },
    signal,
  );
  return settled ?? {
    status: "pending",
    message:
      "用户还没作答。按你自己的判断继续或者先收尾,**不要再问一遍** —— 他答了之后答案会自己送到这次对话里。",
  };
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

/**
 * 选择卡的结果:**答案给模型,卡片身份只进 UI 存档。**
 *
 * `question_id` 是"去轮询"那条协议的残留,对模型是噪音 —— 它拿到的该是"用户选了什么",
 * 不是一个它做不了任何事的 id(见 test/await-user-cards)。
 *
 * 但界面需要它:同一次作答在对话里会留下两份痕迹 —— 这条工具结果,和后端送回会话的那条
 * 回执消息。阻塞那条路上两份都在,画两遍;超时那条路上工具结果是 `pending`,回执是唯一
 * 记录,必须画。界面靠这个 id 分辨这两种情形,而**猜错的方向是把唯一那份也藏掉**。
 *
 * 所以两份不一样,而这正是 `AgentToolResult` 那个 content / details 分法的用途 ——
 * `imageResult` 早就是这么做的(图片本身不进 details,只记张数)。
 */
function answerResult(data: unknown, questionId: string): AgentToolResult<{ data: unknown }> {
  const forUi = data && typeof data === "object" ? { ...(data as object), question_id: questionId } : data;
  return {
    content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    details: { data: forUi },
  };
}

interface ToolImage { mime_type: string; data: string }

/**
 * 带图的结果:文字照旧,图片作为**视觉输入**跟在后面 —— 模型能看见它,而不是读到一串 base64。
 *
 * `details` 里不放图片本身,只记张数:details 会原样发给后端存进这次对话的记录,一张图几十 KB,
 * 建模时一轮几十张,记录会被撑成几 MB。给 UI 的是"看了几张",画面本身属于那一刻的模型。
 */
function imageResult(data: unknown, images: ToolImage[]): AgentToolResult<{ data: unknown; images: number }> {
  return {
    content: [
      { type: "text", text: JSON.stringify(data, null, 2) },
      ...images.map((image) => ({ type: "image" as const, data: image.data, mimeType: image.mime_type })),
    ],
    details: { data, images: images.length },
  };
}

interface ToolSpec {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  confirmation?: boolean;
  awaits_answer?: boolean;
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
  separate_audio: "分离人声与背景音",
  denoise_audio: "降噪",
  generate_image: "生成图片",
  generate_video: "生成视频",
  generate_sound: "生成音乐/音效",
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
          }, signal)) as { result?: unknown; error?: string; images?: ToolImage[] };
          if (response?.error) throw new Error(response.error);
          if (response?.images?.length) return imageResult(response.result ?? null, response.images);
          if (spec.awaits_answer) {
            // 选择卡:调用只立起了卡,这一轮停在这里等用户挑 —— 答案于是作为**工具结果**
            // 回到它被问的那个位置,不用靠一条伪造的用户消息把模型重新叫醒。
            const card = (response?.result ?? {}) as { question_id?: string; error?: string };
            // 没有会话上下文时后端回的是一句 error(飞书 / 外部客户端),照原样给模型。
            if (!card.question_id) return jsonResult(response?.result ?? null);
            return answerResult(await awaitAnswer(apiBase, token, card.question_id, signal), card.question_id);
          }
          if (!spec.confirmation) return jsonResult(response?.result ?? null);
          // 确认门控:调用只创建了待确认卡,阻塞等用户在 Mosael 里批准后把执行结果给模型。
          const card = (response?.result ?? {}) as { confirmation_id?: string };
          if (!card.confirmation_id) throw new Error("确认卡创建失败(缺 confirmation_id)");
          return jsonResult(await awaitConfirmation(apiBase, token, card.confirmation_id, signal));
        },
      };
    });
}
