/**
 * 每一处接着哪段对话 —— **只记在这个窗口、这一次运行里**(sessionStorage,ADR 0044 §3 和维护者 2026-10-07 的修订)。
 *
 * 一处地方第一次打开智能体时是一段**还没建出来的新对话**(草稿):库里没有这一行、历史里也没有它。这次运行里它记着你在哪段
 * —— 收起再打开面板、换个页面再回来,还是那段(或者还是那段没发出去的草稿)。重启应用、开一个新窗口,每一处又从草稿开始;
 * 聊过的都在历史里(「这里的对话」「其他对话」、AI Studio 的列表)。
 *
 * 为什么是 sessionStorage 而不是模块里的变量:同一个窗口里重新加载页面(开发时、出错后点「重新加载」)不该把你正在聊的
 * 那段丢掉,而它跟着窗口走、窗口关了就没 —— 正是「这一次运行」。也正因为它不跨窗口,两个窗口各接各的,不再用 storage
 * 事件互相拽。
 *
 * 只存两样:每一处**明确选过 / 用上了**的那段的 id(没有 = 草稿),和草稿上已经选好的会话设置(模型、思考档位……)——
 * 设置在草稿上照样能选,第一句话发出去建会话时一起带上,不为了记一个选择先建一段空对话。
 */

import type { components } from "@/api/generated/schema";
import { placeKey, type AgentPlace } from "@/features/agent/places";

type AgentSessionCreate = components["schemas"]["AgentSessionCreate"];

/** 草稿上能先选好的会话设置 —— 建会话时一起带上(见 `ensureAgentSession`)。 */
export type AgentDraftSettings = Partial<
  Pick<AgentSessionCreate, "provider_profile_id" | "model" | "thinking_level" | "permission_mode" | "analysis_video_mode">
>;

const SESSION_PREFIX = "mosael.agent.session.";
const DRAFT_PREFIX = "mosael.agent.draft.";

export function agentSessionSelectionKey(workspaceId: string, place: AgentPlace): string {
  return `${SESSION_PREFIX}${workspaceId}.${placeKey(place)}`;
}

function draftSettingsKey(workspaceId: string, place: AgentPlace): string {
  return `${DRAFT_PREFIX}${workspaceId}.${placeKey(place)}`;
}

export function generationSessionSelectionKey(workspaceId: string): string {
  return `mosael.generation.session.${workspaceId}`;
}

// —— 存储:sessionStorage;拿不到(隐私模式、被禁用)时退回这个窗口的内存 —— 至少这一个窗口里各处一致 ——

const memory = new Map<string, string>();

function store(): Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length"> {
  try {
    const storage = window.sessionStorage;
    storage.getItem("");
    return storage;
  } catch {
    return {
      getItem: (key) => memory.get(key) ?? null,
      setItem: (key, value) => void memory.set(key, value),
      removeItem: (key) => void memory.delete(key),
      key: (index) => [...memory.keys()][index] ?? null,
      get length() {
        return memory.size;
      },
    };
  }
}

const listeners = new Set<() => void>();

function changed() {
  for (const listener of listeners) listener();
}

export function subscribeSelections(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// —— 选择 ——

/** 这一处接着的那段的 id;空串 = 草稿(还没有这段对话)。 */
export function readChoice(workspaceId: string, place: AgentPlace): string {
  try {
    return store().getItem(agentSessionSelectionKey(workspaceId, place)) ?? "";
  } catch {
    return "";
  }
}

function writeChoice(workspaceId: string, place: AgentPlace, sessionId: string) {
  if (readChoice(workspaceId, place) === sessionId) return;
  const key = agentSessionSelectionKey(workspaceId, place);
  try {
    if (sessionId) store().setItem(key, sessionId);
    else store().removeItem(key);
  } catch {
    // 配额满了:这一处这次没记住,下次打开是草稿 —— 不比丢掉一句话糟。
  }
  changed();
}

/**
 * 在这一处接着这段对话:写这一处的选择,**不碰它的家**(ADR 0044 拍板 4、5、6 是同一个动作)。从「其他对话」里挑一段、
 * 智能体带着对话跳过来、AI Studio 的「回到那里」都是它。
 */
export function adoptAgentSession(workspaceId: string, place: AgentPlace, sessionId: string): void {
  writeChoice(workspaceId, place, sessionId);
}

/** 「新对话」:这一处换成一段草稿。什么都不建 —— 第一句话发出去才建,家就是这一处。别处不受影响。 */
export function startAgentDraft(workspaceId: string, place: AgentPlace): void {
  writeChoice(workspaceId, place, "");
}

/** 这些对话删掉了:指着它们的选择全清掉(扫这个工作区下所有地方的键),那几处回到草稿。 */
export function forgetChoices(workspaceId: string, sessionIds: readonly string[]): void {
  if (sessionIds.length === 0) return;
  const prefix = `${SESSION_PREFIX}${workspaceId}.`;
  const storage = store();
  const stale: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(prefix) && sessionIds.includes(storage.getItem(key) ?? "")) stale.push(key);
  }
  if (stale.length === 0) return;
  for (const key of stale) storage.removeItem(key);
  changed();
}

// —— 草稿上的会话设置 ——

const EMPTY_SETTINGS: AgentDraftSettings = Object.freeze({});
//: useSyncExternalStore 要同一份快照对同一个值:按存储里的原文缓存解析结果。
const parsed = new Map<string, { raw: string; value: AgentDraftSettings }>();

export function readDraftSettings(workspaceId: string, place: AgentPlace): AgentDraftSettings {
  const key = draftSettingsKey(workspaceId, place);
  let raw = "";
  try {
    raw = store().getItem(key) ?? "";
  } catch {
    return EMPTY_SETTINGS;
  }
  if (!raw) return EMPTY_SETTINGS;
  const cached = parsed.get(key);
  if (cached?.raw === raw) return cached.value;
  let value: AgentDraftSettings = EMPTY_SETTINGS;
  try {
    value = JSON.parse(raw) as AgentDraftSettings;
  } catch {
    value = EMPTY_SETTINGS;
  }
  parsed.set(key, { raw, value });
  return value;
}

export function updateDraftSettings(workspaceId: string, place: AgentPlace, patch: AgentDraftSettings): void {
  const next = { ...readDraftSettings(workspaceId, place), ...patch };
  try {
    store().setItem(draftSettingsKey(workspaceId, place), JSON.stringify(next));
  } catch {
    // 存不进去就只在这一刻生效 —— 下一次渲染读不回来,选择器回到默认。
  }
  changed();
}

/** 草稿建成了会话,设置跟着带进去了:清掉,下一段草稿从默认开始。 */
export function clearDraftSettings(workspaceId: string, place: AgentPlace): void {
  try {
    store().removeItem(draftSettingsKey(workspaceId, place));
  } catch {
    return;
  }
  changed();
}
