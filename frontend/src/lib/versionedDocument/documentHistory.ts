/**
 * 一份文档的撤销 / 重做:一摞快照,**一次手势 = 一步**。
 *
 * 三条边界(和画板的 canvasHistory 同一套道理,这里只管「整份文档的快照」那一种步):
 *
 *  · **一串连续改动并成一步。** 拖一个滑块、在数字框里连着敲,每一下都是一次改动;一次一步的话,
 *    用户得按几十下撤销才回得到手势之前,而 50 步的上限一次拖动就用完。调用方给同一个 `gesture`
 *    且两次改动挨得够近(`GESTURE_GAP_MS` 之内),就并进上一步 —— 上一步记的仍是手势**开始之前**那一份。
 *  · **有新改动时清掉重做。** 撤回去两步又改了别的,那两步就接不上了。
 *  · **换成服务端那份时整摞清掉(`reset`)。** 摞里记的是被换掉的那份,留着的话撤一下就把旧内容写回去、
 *    再带着新底子存上 —— 绕过冲突检查把别人的改动静默盖掉。
 */

/** 同一个手势里两次改动最多隔多久还算「同一下」。 */
export const GESTURE_GAP_MS = 800;
/** 最多记多少步。 */
export const HISTORY_LIMIT = 50;

export interface DocumentHistory<T> {
  past: readonly T[];
  present: T;
  future: readonly T[];
  /** 上一次改动属于哪个手势、什么时候 —— 用来判断下一次要不要并进去。 */
  last: { gesture: string; at: number } | null;
}

export function startHistory<T>(present: T): DocumentHistory<T> {
  return { past: [], present, future: [], last: null };
}

/**
 * 记下一次改动。`gesture`:这次改动属于哪一个连续动作(例如 `"inspector:obj-1:position"`);
 * 不给 = 自成一步。`at`:改动的时刻(毫秒),测试里显式给。
 */
export function record<T>(
  history: DocumentHistory<T>,
  next: T,
  { gesture, at = Date.now(), limit = HISTORY_LIMIT }: { gesture?: string; at?: number; limit?: number } = {},
): DocumentHistory<T> {
  const continues =
    gesture !== undefined &&
    history.last !== null &&
    history.last.gesture === gesture &&
    at - history.last.at <= GESTURE_GAP_MS &&
    history.future.length === 0;
  return {
    past: continues ? history.past : [...history.past, history.present].slice(-limit),
    present: next,
    future: [],
    last: gesture === undefined ? null : { gesture, at },
  };
}

export function undo<T>(history: DocumentHistory<T>): DocumentHistory<T> {
  const previous = history.past[history.past.length - 1];
  if (previous === undefined) return history;
  return { past: history.past.slice(0, -1), present: previous, future: [history.present, ...history.future], last: null };
}

export function redo<T>(history: DocumentHistory<T>): DocumentHistory<T> {
  const [next, ...rest] = history.future;
  if (next === undefined) return history;
  return { past: [...history.past, history.present], present: next, future: rest, last: null };
}

/** 换成别的一份(服务端版本、恢复的草稿)作为新的起点:撤销 / 重做都清空。 */
export function reset<T>(present: T): DocumentHistory<T> {
  return startHistory(present);
}
