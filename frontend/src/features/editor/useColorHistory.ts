import React from "react";

/** 调色独立撤销栈。按 clip 存快照(只关心 color + filter 两个视觉字段),每次编辑前
 *  snapshot() 记一步,undo/redo 通过再发一次 setEffects 恢复。与时间线全局撤销解耦。 */

type Effects = Record<string, unknown>;

/** 把一次编辑的可撤销状态序列化(稳定字符串,便于比较与深拷贝)。 */
export function serializeColor(effects: Effects | undefined): string {
  return JSON.stringify({ color: effects?.color ?? null, filter: effects?.filter ?? null });
}

/** 把快照还原进完整 effects(保留 pip/text 等非调色字段)。 */
export function restoreColor(effects: Effects, serialized: string): Effects {
  const { color, filter } = JSON.parse(serialized) as { color: unknown; filter: unknown };
  const next = { ...effects };
  if (color) next.color = color;
  else delete next.color;
  if (filter) next.filter = filter;
  else delete next.filter;
  return next;
}

interface Stack {
  past: string[];
  future: string[];
}

export interface ColorHistory {
  snapshot: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

export function useColorHistory(
  clipId: string,
  effects: Effects,
  onSetEffects: (clipId: string, effects: Effects) => void,
): ColorHistory {
  const stacks = React.useRef(new Map<string, Stack>());
  const [, bump] = React.useReducer((n: number) => n + 1, 0);

  const stackFor = (id: string): Stack => {
    let s = stacks.current.get(id);
    if (!s) {
      s = { past: [], future: [] };
      stacks.current.set(id, s);
    }
    return s;
  };

  const snapshot = () => {
    const s = stackFor(clipId);
    s.past.push(serializeColor(effects));
    s.future = [];
    bump();
  };

  const undo = () => {
    const s = stackFor(clipId);
    const prev = s.past.pop();
    if (prev === undefined) return;
    s.future.push(serializeColor(effects));
    onSetEffects(clipId, restoreColor(effects, prev));
    bump();
  };

  const redo = () => {
    const s = stackFor(clipId);
    const next = s.future.pop();
    if (next === undefined) return;
    s.past.push(serializeColor(effects));
    onSetEffects(clipId, restoreColor(effects, next));
    bump();
  };

  const s = stackFor(clipId);
  return { snapshot, undo, redo, canUndo: s.past.length > 0, canRedo: s.future.length > 0 };
}
