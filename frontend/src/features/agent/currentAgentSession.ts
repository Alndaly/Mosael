/**
 * 「这一处接着哪段对话」—— 每一处地方各有一个答案(ADR 0044 §3,地方见 places)。
 *
 * **为什么要有唯一来源。** AI Studio、各页面的助手面板(剪辑 / 笔记 / 画板 / 工作流 / 3D 场景 / 工作台的「助手」)、免提浮标、
 * 智能体发起的页面跳转(open_view)都对着「当前对话」干活。此前它们各读各的:面板回落到清单第一条却不告诉别人,对浮标说话
 * 新建了第二条,智能体要求的跳转没人执行。所以同一处的这几样读的是同一个答案 —— 只是答案不再是「整个工作区一个」:剪辑
 * 里聊的不接着笔记里那段,在一处点「新对话」别处不跟着换(那是 0044 之前的毛病)。
 *
 * **形状。** 存的只有一样:这一处**明确选过 / 用上了**的那段的 id(sessionStorage,按「工作区 + 地方」分键,见
 * sessionSelection —— 只记这一次运行)。没有就是**草稿**:一段还没建出来的新对话,库里没有、历史里也没有。第一句话发出去
 * (`ensureAgentSession`)才建,家就是这一处;草稿上先选好的模型、思考档位……一起带上。所以打开智能体、点「新对话」、对浮标
 * 说话之前,都不会留下空对话(维护者 2026-10-07 的修订:每次初次打开智能体是一段未创建的新对话)。
 *
 * 选过的那段家在别处也照样是它(在这里接着聊,拍板 4):读它自己的 `["agent-session", id]`(面板本来就在轮询它),不依赖
 * 「家在这里的」那份清单。它被删了(404)就放下选择,回到草稿。
 *
 * **同事共享来的对话只能看**(后端 domain/agent/sessions 的写闸,`is_mine` 是它给的答案)。「能不能往里写」只在这里判一次
 * (`isViewOnly`):明确点开一段共享来的,它就是这一处的当前对话(看它);`ensureAgentSession` 遇到只读的就拒
 * (`ViewOnlySessionError`),**不悄悄新建一段** —— 新建会把这句话发进一段他没看着的对话里,而屏幕上还停在别人那段。
 */

import React from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import {
  type AgentSession,
  createAgentSession,
  getAgentSession,
  isNotFound,
  listAgentSessions,
  moveAgentHomes,
  updateAgentSession,
} from "@/api/client";
import type { components } from "@/api/generated/schema";
import { STUDIO_PLACE, placeKey, placePayload, samePlace, type AgentPlace } from "@/features/agent/places";
import {
  type AgentDraftSettings,
  adoptAgentSession,
  clearDraftSettings,
  forgetChoices,
  moveChoices,
  readChoice,
  readDraftSettings,
  startAgentDraft,
  subscribeSelections,
  updateDraftSettings,
} from "@/features/agent/sessionSelection";

export { adoptAgentSession, startAgentDraft } from "@/features/agent/sessionSelection";

type AgentSessionUpdate = components["schemas"]["AgentSessionUpdate"];

const EMPTY: AgentSession[] = [];

/** 整个工作区的对话(AI Studio 的列表、面板下拉里的「其他对话」)。各处的清单都以它为前缀 —— 失效它就一起失效。 */
export function agentSessionsQueryKey(workspaceId: string) {
  return ["agent-sessions", workspaceId] as const;
}

/** 家在这一处的对话(面板下拉里的「这里的对话」)。 */
export function agentSessionsHereKey(workspaceId: string, place: AgentPlace) {
  return ["agent-sessions", workspaceId, placeKey(place)] as const;
}

/** 同事共享来、只能看的对话。只认后端明说「不是你的」—— 没说的(刚建、还没回来)当作自己的。 */
export function isViewOnly(session: { is_mine?: boolean } | null | undefined): boolean {
  return session?.is_mine === false;
}

/** 要往一段只读的对话里写。带着给人看的那句话的 key,由界面翻。 */
export class ViewOnlySessionError extends Error {
  readonly messageKey = "chatSessionReadOnly" as const;

  constructor() {
    super("agent session is view-only");
    this.name = "ViewOnlySessionError";
  }
}

/**
 * 在 AI Studio 打开某一段对话:AI Studio 那一处接着它(不改它的家),再跳过去。设置 → 技能里「智能体起草」那个来源标签
 * 用它跳回建技能的那段对话。
 */
export function openAgentSession(workspaceId: string, sessionId: string): void {
  adoptAgentSession(workspaceId, STUDIO_PLACE, sessionId);
  window.location.hash = "#/ai";
}

/**
 * 「带着这段话去开一段新对话」的信箱事件(见 lib/deepLink 的 emitOpenEvent):发出的一方往里放草稿,AI Studio 挂上以后取走、
 * 填进输入框。不替他发送 —— 他多半还要说想让智能体做什么。发的一方先 `startAgentDraft(工作区, STUDIO_PLACE)`:
 * AI Studio 换成一段草稿,第一句话发出去才建。
 */
export const AGENT_DRAFT_EVENT = "mosael:agent-draft";

/** 草稿建成会话:家是这一处,草稿上选好的设置一起带上;建好就是这一处的当前对话。 */
async function createHere(qc: QueryClient, workspaceId: string, place: AgentPlace): Promise<AgentSession> {
  const created = await createAgentSession({
    workspace_id: workspaceId,
    home: placePayload(place),
    ...readDraftSettings(workspaceId, place),
  });
  clearDraftSettings(workspaceId, place);
  // 先把它放进清单和详情的缓存再选中:等重拉的那一下里新 id 找不到,这一处会闪回草稿 —— 看起来就像那句话没发出去。
  qc.setQueryData(["agent-session", created.id], created);
  qc.setQueryData<AgentSession[]>(agentSessionsHereKey(workspaceId, place), (old) => [
    created,
    ...(old ?? []).filter((item) => item.id !== created.id),
  ]);
  adoptAgentSession(workspaceId, place, created.id);
  void qc.invalidateQueries({ queryKey: agentSessionsQueryKey(workspaceId) });
  return created;
}

const ensuring = new Map<string, Promise<AgentSession>>();

/**
 * 要**用**这一处的当前对话了(发消息、对浮标说话):有就是它,是草稿就在这一处建一段;它是同事共享来只能看的,就拒
 * (`ViewOnlySessionError`)—— 不替他另建一段,那句话该发在哪儿由他自己定。
 *
 * 同一处同时只跑一个:面板发送和浮标说话撞在同一刻时,不该各建一段。不同的地方各建各的。
 */
export function ensureAgentSession(qc: QueryClient, workspaceId: string, place: AgentPlace): Promise<AgentSession> {
  const slot = `${workspaceId}|${placeKey(place)}`;
  const inflight = ensuring.get(slot);
  if (inflight) return inflight;
  const job = (async () => {
    const choice = readChoice(workspaceId, place);
    if (choice) {
      let session = qc.getQueryData<AgentSession>(["agent-session", choice]) ?? null;
      if (!session) {
        try {
          session = await qc.fetchQuery({
            queryKey: ["agent-session", choice],
            queryFn: () => getAgentSession(choice),
            staleTime: 0,
          });
        } catch (error) {
          // 选着的那段被删了:放下选择,这一句开一段新的。别的失败(断网)照原样报 —— 不能因为一次没连上就另开一段。
          if (!isNotFound(error)) throw error;
          forgetChoices(workspaceId, [choice]);
          session = null;
        }
      }
      if (session) {
        if (isViewOnly(session)) throw new ViewOnlySessionError();
        return session;
      }
    }
    return createHere(qc, workspaceId, place);
  })().finally(() => ensuring.delete(slot));
  ensuring.set(slot, job);
  return job;
}

let moving: Promise<unknown> = Promise.resolve();

/**
 * 一处地方换了 id —— ComfyUI 那张第一次存盘、改名、挪文件夹(工作台的桥报来的,ADR 0044 §9)。这个窗口里那一处的选择和
 * 草稿设置**当场**挪过去(面板换到新地方时还是那段,不闪回草稿),再请后端把家在旧地方的对话挪过去,挪完重读清单。
 *
 * 一个接一个地挪:存一张没存过的,桥可能先后报两条(改了名、存上了),后一条要等前一条在后端挪完,不然它挪的时候家还在原处。
 */
export function moveAgentPlace(qc: QueryClient, workspaceId: string, from: AgentPlace, to: AgentPlace): Promise<void> {
  if (samePlace(from, to)) return Promise.resolve();
  moveChoices(workspaceId, from, to);
  const moved = moving
    .then(() => moveAgentHomes({ workspace_id: workspaceId, kind: from.kind, from_id: from.id, to_id: to.id }))
    .then(() => qc.invalidateQueries({ queryKey: agentSessionsQueryKey(workspaceId) }));
  moving = moved.catch(() => undefined);
  return moved;
}

/** 这些对话删掉了:指着它们的选择全清掉(那几处回到草稿),缓存里也拿掉。 */
function forgetSessions(qc: QueryClient, workspaceId: string, ids: readonly string[]) {
  if (ids.length === 0) return;
  // 先从清单里拿掉:服务端清单重拉回来之前,不能还列着一段刚删掉的对话。
  qc.setQueriesData<AgentSession[]>({ queryKey: agentSessionsQueryKey(workspaceId) }, (old) =>
    old?.filter((item) => !ids.includes(item.id)),
  );
  forgetChoices(workspaceId, ids);
  for (const id of ids) {
    for (const family of ["agent-messages", "agent-session", "agent-queue"]) {
      qc.removeQueries({ queryKey: [family, id] });
    }
  }
}

/** 整个工作区的对话(最近活跃在前)。AI Studio 的列表一直要;面板只在下拉展开(或空态要说「接着别处的」)时才要。 */
export function useAgentSessions(workspaceId: string, { enabled = true, pollList }: { enabled?: boolean; pollList?: number } = {}) {
  return useQuery({
    queryKey: agentSessionsQueryKey(workspaceId),
    queryFn: () => listAgentSessions(workspaceId),
    enabled,
    refetchInterval: pollList,
  });
}

export interface CurrentAgentSession {
  /** 这一处。 */
  place: AgentPlace;
  /** 家在这一处的对话(最近活跃在前)。 */
  here: AgentSession[];
  /** 「这里的对话」还没读到 —— 这时 `here` 为空不代表这里一段都没有。 */
  listPending: boolean;
  listLoaded: boolean;
  /** 这一处的当前对话;`null` 是草稿(还没建出来),或者选着的那段还在读(见 `resolving`)。 */
  session: AgentSession | null;
  /** 选着一段、还没读到它 —— 这时 `session` 为空不代表是草稿。 */
  resolving: boolean;
  /** 当前对话是同事共享来只能看的:输入区、会话设置、拍板的按钮都不给(见 `isViewOnly`)。 */
  readOnly: boolean;
  /** 在这里接着这段(家不变)。 */
  select: (sessionId: string) => void;
  /** 「新对话」:这一处换成草稿,什么都不建。 */
  startDraft: () => void;
  /** 删掉了这些对话之后调:指着它们的选择回到草稿。 */
  forget: (ids: readonly string[]) => void;
  /** 要用当前对话了:有就是它,草稿就在这一处建一段。见 `ensureAgentSession`。 */
  ensure: () => Promise<AgentSession>;
}

export function useCurrentAgentSession(
  workspaceId: string,
  place: AgentPlace,
  { pollList }: { /** 清单轮询间隔:标题在第一轮对话之后才起好,常驻的那一行要跟上。 */ pollList?: number } = {},
): CurrentAgentSession {
  const qc = useQueryClient();
  const choice = React.useSyncExternalStore(subscribeSelections, () => readChoice(workspaceId, place));
  const here = useQuery({
    queryKey: agentSessionsHereKey(workspaceId, place),
    queryFn: () => listAgentSessions(workspaceId, place),
    refetchInterval: pollList,
  });
  //: 选着的那段读它自己的详情 —— 家在别处的(在这里接着聊的)不在「这里的对话」里。和面板的 `live` 同一个键,不多打请求。
  const chosen = useQuery({
    queryKey: ["agent-session", choice],
    queryFn: () => getAgentSession(choice),
    enabled: Boolean(choice),
    retry: (count, error) => !isNotFound(error) && count < 2,
  });
  const listed = here.data?.find((item) => item.id === choice) ?? null;
  const session = choice ? chosen.data ?? listed : null;
  const gone = Boolean(choice) && chosen.isError && isNotFound(chosen.error);
  React.useEffect(() => {
    if (gone) forgetChoices(workspaceId, [choice]);
  }, [gone, choice, workspaceId]);

  const select = React.useCallback((sessionId: string) => adoptAgentSession(workspaceId, place, sessionId), [workspaceId, place]);
  const startDraft = React.useCallback(() => startAgentDraft(workspaceId, place), [workspaceId, place]);
  const forget = React.useCallback((ids: readonly string[]) => forgetSessions(qc, workspaceId, ids), [qc, workspaceId]);
  const ensure = React.useCallback(() => ensureAgentSession(qc, workspaceId, place), [qc, workspaceId, place]);

  return {
    place,
    here: here.data ?? EMPTY,
    listPending: here.isPending,
    listLoaded: here.isSuccess,
    session,
    resolving: Boolean(choice) && !session && !chosen.isError,
    readOnly: isViewOnly(session),
    select,
    startDraft,
    forget,
    ensure,
  };
}

/** 选择器读的那几样设置:有会话读会话上的,草稿读草稿上已经选好的。 */
export interface AgentSettingsView {
  provider_profile_id?: string | null;
  model?: string | null;
  thinking_level?: string | null;
  permission_mode?: string | null;
  analysis_video_mode?: string | null;
  /** 档位是谁开的(只有会话上有)。 */
  mode_set_by?: string | null;
}

/**
 * 四个设置选择器共用:读(会话上的,或者草稿上的)和写(`useUpdateAgentSession`)。草稿上的设置只记在这个窗口里,
 * 第一句话发出去建会话时一起带上。
 */
export function useSessionSettings(workspaceId: string, place: AgentPlace, session: AgentSession | null) {
  const draft = React.useSyncExternalStore(subscribeSelections, () => readDraftSettings(workspaceId, place));
  const settings: AgentSettingsView = session ?? draft;
  const update = useUpdateAgentSession(workspaceId, place, session);
  return { settings, update };
}

/**
 * 改会话设置(模型、权限模式、思考档位、分析方式)。四个选择器共用这一个。
 *
 * **草稿上也能选**,而且**不为此建一段对话**:选择记在草稿上,第一句话发出去建会话时一起带上(见 `createHere`)—— 此前
 * 没有会话时选一下就先建一段空的,历史里于是攒下一排「新对话」。只读的对话不写(和 `ensureAgentSession` 同一条):选择器在
 * 只读会话里本就不出现,这里是最后一道。
 */
export function useUpdateAgentSession(workspaceId: string, place: AgentPlace, session: AgentSession | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (patch: AgentSessionUpdate) => {
      if (!session) {
        updateDraftSettings(workspaceId, place, patch as AgentDraftSettings);
        return "";
      }
      if (isViewOnly(session)) throw new ViewOnlySessionError();
      await updateAgentSession(session.id, patch);
      return session.id;
    },
    onSuccess: (sessionId) => {
      if (!sessionId) return;
      void qc.invalidateQueries({ queryKey: ["agent-session", sessionId] });
      void qc.invalidateQueries({ queryKey: agentSessionsQueryKey(workspaceId) });
    },
  });
}
