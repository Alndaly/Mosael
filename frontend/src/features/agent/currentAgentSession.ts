/**
 * 「当前是哪个智能体会话」—— 整个应用只有这一个答案。
 *
 * **为什么要有唯一来源。** AI 工作台、画布助手(工作流 / 画板 / 剪辑 / 3D 共用)、免提浮标、
 * 智能体发起的页面跳转(open_view)都对着「当前会话」干活。此前四处各读各的:两个面板在没有
 * 存储时回落到清单第一条,却不告诉别人;浮标和跳转只读 localStorage —— 于是面板正显示着一条
 * 会话,对浮标说话却新建了第二条,智能体要求的跳转也没人执行。反过来浮标建了新会话,已经打开
 * 的面板只在挂载时读过一次,不跟着切。
 *
 * **形状。** 存储的只有一样东西:用户**明确选过**的会话 id(localStorage,按工作区分键)。
 * 「当前会话」由它和会话清单**现算**:选过的那条在清单里就是它,否则是清单第一条(最近活跃)。
 * 清单是同一个 React Query 键,所以四处算出来的是同一条;选择的变化同一窗口靠这里的广播、
 * 跨窗口靠 storage 事件,不再轮询。
 *
 * **回落不写回,用上才写回。** 只是**看着**第一条时不把它记成选择:
 * - 写回的是一个**推导值**,而推导依据的清单可能是旧的 —— 别的窗口刚建了一条、这边清单还没
 *   刷新,这边就会把「第一条」写回去,storage 事件再把那个窗口也拽走,两边来回抢;
 * - 四处用同一个清单、同一条规则现算,不写也看到同一条,写回换不来一致性。
 * 代价是「从没选过」时当前会话跟着最近活跃走。一旦**用上**它 —— 发消息、对浮标说话、改会话
 * 设置(都经过 `ensureAgentSession`)—— 这条就被记成选择,之后不会再被别的会话顶掉。
 *
 * **同事共享来的对话只能看**(后端 domain/agent/sessions 的写闸,`is_mine` 是它给的答案)。「能不能往里写」
 * 只在这里判一次(`isViewOnly`),三处用它:
 * - 回落只落在**自己的**对话上:没选过时的「当前会话」是一个猜测 —— 猜他要接着聊哪一条,而别人的那条他
 *   接不下去。明确点开一条共享来的,它才是当前会话(看它);
 * - `ensureAgentSession` 遇到只读的当前会话就拒(`ViewOnlySessionError`),**不悄悄新建一条** —— 新建会把
 *   这句话发进一条他没看着的对话里,而屏幕上还停在别人那条;
 * - 会话设置的写入(`useUpdateAgentSession`)同一条规矩。界面据 `readOnly` 把输入区换成只读说明。
 */

import React from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient, type UseMutationResult } from "@tanstack/react-query";

import {
  type AgentSession,
  createAgentSession,
  listAgentSessions,
  updateAgentSession,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
import { agentSessionSelectionKey } from "@/features/agent/sessionSelection";

type AgentSessionUpdate = components["schemas"]["AgentSessionUpdate"];

const EMPTY: AgentSession[] = [];

export function agentSessionsQueryKey(workspaceId: string) {
  return ["agent-sessions", workspaceId] as const;
}

/** 同事共享来、只能看的对话。只认后端明说「不是你的」—— 没说的(刚建、还没回来)当作自己的。 */
export function isViewOnly(session: { is_mine?: boolean } | null | undefined): boolean {
  return session?.is_mine === false;
}

/** 要往一条只读的对话里写。带着给人看的那句话的 key,由界面翻。 */
export class ViewOnlySessionError extends Error {
  readonly messageKey = "chatSessionReadOnly" as const;

  constructor() {
    super("agent session is view-only");
    this.name = "ViewOnlySessionError";
  }
}

/** 选过的那条优先;没选过、或选的那条已经不在清单里,就是**自己的**第一条(清单按最近活跃排)。 */
export function resolveCurrentSession(sessions: readonly AgentSession[], choice: string): AgentSession | null {
  return sessions.find((item) => item.id === choice) ?? sessions.find((item) => !isViewOnly(item)) ?? null;
}

// —— 选择本身:localStorage + 同窗口广播 ——

const listeners = new Set<() => void>();

function readChoice(workspaceId: string): string {
  try {
    return window.localStorage.getItem(agentSessionSelectionKey(workspaceId)) ?? "";
  } catch {
    return "";
  }
}

function writeChoice(workspaceId: string, sessionId: string) {
  if (readChoice(workspaceId) === sessionId) return;
  const key = agentSessionSelectionKey(workspaceId);
  try {
    if (sessionId) window.localStorage.setItem(key, sessionId);
    else window.localStorage.removeItem(key);
  } catch {
    // 存不进去(隐私模式、配额)时,本窗口的广播照发 —— 至少这一个窗口里四处仍然一致。
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // 同一个文档里的写入不触发 storage 事件(上面那份广播管);它只报别的窗口写的。
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

// —— 改变「当前会话」的三种动作 ——

async function createAndSelect(qc: QueryClient, workspaceId: string): Promise<AgentSession> {
  //: 家先一律是 AI Studio(ADR 0044 第一步:后端记住在哪开的;各处说自己在哪是第二步)。
  const created = await createAgentSession({ workspace_id: workspaceId, home: { kind: "studio", id: "" } });
  // 先把新会话放进清单再选中:等重拉的那一下里新 id 在清单里找不到,「当前会话」会瞬间回落到
  // 第一条 —— 看起来就像点了没反应。
  qc.setQueryData<AgentSession[]>(agentSessionsQueryKey(workspaceId), (old) => [
    created,
    ...(old ?? []).filter((item) => item.id !== created.id),
  ]);
  writeChoice(workspaceId, created.id);
  void qc.invalidateQueries({ queryKey: agentSessionsQueryKey(workspaceId) });
  return created;
}

/**
 * 新开一条对话并设为当前 —— 给「从别处带着东西来问智能体」用(内嵌浏览器顶栏「交给智能体」)。
 * 和会话列表上的「新建」是同一个动作,只是不在 hook 里。
 */
export function startNewAgentSession(qc: QueryClient, workspaceId: string): Promise<AgentSession> {
  return createAndSelect(qc, workspaceId);
}

/**
 * 「带着这段话去开一条新对话」的信箱事件(见 lib/deepLink 的 emitOpenEvent):发出的一方往里放草稿,
 * AI 工作台挂上以后取走、填进输入框。不替他发送 —— 他多半还要说想让智能体做什么。
 */
/**
 * 打开某一次对话:记成**明确选过**的当前会话,再跳到 AI Studio(它照「当前会话」显示)。设置 → 技能里
 * 「智能体起草」那个来源标签用它跳回建技能的那段对话。那段对话不在清单里(删了、没共享给他)时,
 * AI Studio 照常回落,和别处一样。
 */
export function openAgentSession(workspaceId: string, sessionId: string): void {
  writeChoice(workspaceId, sessionId);
  window.location.hash = "#/ai";
}

export const AGENT_DRAFT_EVENT = "mosael:agent-draft";

const ensuring = new Map<string, Promise<AgentSession>>();

/**
 * 要**用**当前会话了:有就是它(并把它记成选择),没有就建一条;它是同事共享来只能看的,就拒
 * (`ViewOnlySessionError`)—— 不替他另建一条,那句话该发在哪儿由他自己定。
 *
 * 同一工作区同时只跑一个:面板发送和浮标说话撞在同一刻时,不该各建一条。
 */
export function ensureAgentSession(qc: QueryClient, workspaceId: string): Promise<AgentSession> {
  const inflight = ensuring.get(workspaceId);
  if (inflight) return inflight;
  const job = (async () => {
    const choice = readChoice(workspaceId);
    const cached = qc.getQueryData<AgentSession[]>(agentSessionsQueryKey(workspaceId));
    // 清单没读过,或者选中的那条不在里面(多半是别的窗口刚建的):先和服务端对一遍再定 ——
    // 否则消息会发进第一条,或者白白再建一条。
    const sessions =
      cached && (!choice || cached.some((item) => item.id === choice))
        ? cached
        : await qc.fetchQuery({
        queryKey: agentSessionsQueryKey(workspaceId),
            queryFn: () => listAgentSessions(workspaceId),
            staleTime: 0,
          });
    const current = resolveCurrentSession(sessions, choice);
    if (!current) return createAndSelect(qc, workspaceId);
    if (isViewOnly(current)) throw new ViewOnlySessionError();
    writeChoice(workspaceId, current.id);
    return current;
  })().finally(() => ensuring.delete(workspaceId));
  ensuring.set(workspaceId, job);
  return job;
}

/** 这些会话被删掉了。当前那条在其中就放下选择 —— 由同一条规则回落到剩下的第一条。 */
function forgetSessions(qc: QueryClient, workspaceId: string, ids: readonly string[]) {
  if (ids.length === 0) return;
  // 先从清单里拿掉:服务端清单重拉回来之前,回落不能落到一条刚删掉的会话上。
  qc.setQueryData<AgentSession[]>(agentSessionsQueryKey(workspaceId), (old) =>
    old?.filter((item) => !ids.includes(item.id)),
  );
  if (ids.includes(readChoice(workspaceId))) writeChoice(workspaceId, "");
  for (const id of ids) {
    for (const family of ["agent-messages", "agent-session", "agent-queue"]) {
      qc.removeQueries({ queryKey: [family, id] });
    }
  }
}

export interface CurrentAgentSession {
  /** 会话清单(最近活跃在前)。 */
  sessions: AgentSession[];
  /** 清单还没读到 —— 这时 `session` 为空不代表"没有会话"。 */
  listPending: boolean;
  listLoaded: boolean;
  /** 当前会话;清单为空时为 null。 */
  session: AgentSession | null;
  /** 当前会话是同事共享来只能看的:输入区、会话设置、拍板的按钮都不给(见 `isViewOnly`)。 */
  readOnly: boolean;
  select: (sessionId: string) => void;
  /** 删掉了这些会话之后调:当前那条在其中就回落。 */
  forget: (ids: readonly string[]) => void;
  /** 新建一条并设为当前。按钮接它的 isPending。 */
  create: UseMutationResult<AgentSession, Error, void>;
  /** 要用当前会话了:有就是它,没有就建。见 `ensureAgentSession`。 */
  ensure: () => Promise<AgentSession>;
}

export function useCurrentAgentSession(
  workspaceId: string,
  { pollList }: { /** 清单轮询间隔:首条消息会自动改题,常驻的标题要跟上。 */ pollList?: number } = {},
): CurrentAgentSession {
  const qc = useQueryClient();
  const choice = React.useSyncExternalStore(subscribe, () => readChoice(workspaceId));
  const list = useQuery({
    queryKey: agentSessionsQueryKey(workspaceId),
    queryFn: () => listAgentSessions(workspaceId),
    refetchInterval: pollList,
  });
  const sessions = list.data ?? EMPTY;
  const session = resolveCurrentSession(sessions, choice);

  //: 选中的那条不在清单里:可能是别的窗口刚建的、这边清单还旧 —— 重拉一次再说。
  //: 每个 id 只拉一次:真被删掉的话不能一直拉下去。
  const refetchedFor = React.useRef("");
  const found = sessions.some((item) => item.id === choice);
  React.useEffect(() => {
    if (!choice || found || !list.isSuccess || refetchedFor.current === choice) return;
    refetchedFor.current = choice;
    void qc.invalidateQueries({ queryKey: agentSessionsQueryKey(workspaceId) });
  }, [choice, found, list.isSuccess, qc, workspaceId]);

  const create = useMutation<AgentSession, Error, void>({ mutationFn: () => createAndSelect(qc, workspaceId) });
  const select = React.useCallback((sessionId: string) => writeChoice(workspaceId, sessionId), [workspaceId]);
  const forget = React.useCallback((ids: readonly string[]) => forgetSessions(qc, workspaceId, ids), [qc, workspaceId]);
  const ensure = React.useCallback(() => ensureAgentSession(qc, workspaceId), [qc, workspaceId]);

  return {
    sessions,
    listPending: list.isPending,
    listLoaded: list.isSuccess,
    session,
    readOnly: isViewOnly(session),
    select,
    forget,
    create,
    ensure,
  };
}

/**
 * 改会话设置(模型、权限模式、思考档位、分析方式)。四个选择器共用这一个。
 *
 * **还没有会话时也能选**:先按「当前会话」的规则取一条(一条都没有就建),再写进去 —— 此前
 * 没有会话时这几样整块不见,第一条消息只能用默认值发。建会话接口只收模型两栏,其余三项只能
 * PATCH,所以统一走「取/建 → PATCH」一条路,而不是模型走 create、其余走 PATCH 两条。
 * 只读的对话不写(和 `ensureAgentSession` 同一条):选择器在只读会话里本就不出现,这里是最后一道。
 */
export function useUpdateAgentSession(workspaceId: string, session: AgentSession | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: AgentSessionUpdate) => {
      if (isViewOnly(session)) throw new ViewOnlySessionError();
      const target = session ?? (await ensureAgentSession(qc, workspaceId));
      await updateAgentSession(target.id, patch);
      return target.id;
    },
    onSuccess: (sessionId) => {
      void qc.invalidateQueries({ queryKey: ["agent-session", sessionId] });
      void qc.invalidateQueries({ queryKey: agentSessionsQueryKey(workspaceId) });
    },
  });
}
