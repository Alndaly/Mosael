import React from "react";

/**
 * 一格时间线的播放头和选中的那一段(ADR 0030)。**格子和它上方的操作条读同一份**:剪刀切的是播放头所在的那一段、
 * 删除删的是选中的那一段,而按钮在操作条上(用户:「这些按钮放到上方弹窗中去」),状态在格子里 —— 两处各存一份的话,
 * 按钮拿到的播放头永远是上一次的。按时间线 id 存,不进画布数据(它是这一刻的界面状态,不是画板的内容)。
 */
export type SequenceCursor = { time: number; picked: string | null };

const EMPTY: SequenceCursor = { time: 0, picked: null };
const cursors = new Map<string, SequenceCursor>();
const listeners = new Map<string, Set<() => void>>();

export function readSequenceCursor(sequenceId: string): SequenceCursor {
  return cursors.get(sequenceId) ?? EMPTY;
}

export function updateSequenceCursor(sequenceId: string, patch: Partial<SequenceCursor>): void {
  cursors.set(sequenceId, { ...readSequenceCursor(sequenceId), ...patch });
  for (const listener of listeners.get(sequenceId) ?? []) listener();
}

export function useSequenceCursor(sequenceId: string): SequenceCursor {
  const subscribe = React.useCallback((listener: () => void) => {
    const set = listeners.get(sequenceId) ?? new Set();
    set.add(listener);
    listeners.set(sequenceId, set);
    return () => set.delete(listener);
  }, [sequenceId]);
  return React.useSyncExternalStore(subscribe, () => readSequenceCursor(sequenceId));
}

/**
 * 格子里在时间线上做成了一步(剪刀、删除、拖动排序、连线加片段):告诉画布,记进画板的撤销栈(canvasHistory 的
 * 「时间线的一步」)。格子和画布之间只隔这一条通知,格子不必知道画布的撤销栈长什么样。
 */
export type SequenceEditLink = { source: string; target: string; batch?: string };
type SequenceEditListener = (sequenceId: string, revision: number, link?: SequenceEditLink) => void;
const editListeners = new Set<SequenceEditListener>();

/** `revision`:这一步做完之后时间线停在第几版。撤销时带上它 —— 时间线在别处又改过的话,服务端不撤别人的那一步。
 *  `link`:这一步是连了一根线引起的(画布上那根线和时间线上这一段并成撤销里的一步)。 */
export function noteSequenceEdit(sequenceId: string, revision: number, link?: SequenceEditLink): void {
  for (const listener of editListeners) listener(sequenceId, revision, link);
}

export function onSequenceEdit(listener: SequenceEditListener): () => void {
  editListeners.add(listener);
  return () => editListeners.delete(listener);
}

/**
 * 条末尾的「+」:给这条时间线挑一份素材接到末尾(从这张画板上已有的格子里,或素材库里)。挑素材的弹窗在画板那一层
 * (BoardsView),格子够不着 —— 画布把「给这条时间线挑」放进这个 context。没有(单独渲染格子时)就不画「+」。
 * 住在这个不引 UI 的模块里:热更新重跑格子组件时 context 的身份不变(见 app/contextIdentity.test)。
 */
export const SequenceAddContext = React.createContext<((sequenceId: string) => void) | null>(null);
