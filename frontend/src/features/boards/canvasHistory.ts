/**
 * 画布的撤销/重做 —— 一摞快照。
 *
 * 工作流那边的撤销挂在 zustand+zundo 上,因为它的事实来源是 store 里的 graph;画板不是
 * ——**React Flow 的 nodes/edges 才是事实**,画布是从它们序列化出来的。所以这里存的是
 * 序列化后的整份画布,撤销就是把某一份装回去。
 *
 * 三条边界,错了都不会报错:
 *
 *  · **撤销自己造成的变化不能再进历史。** 不拦的话,撤一步会立刻被记成一次新编辑,重做
 *    就永远回不去了 —— 表现是「撤销键按一下就灰了」。
 *  · **一串连续动作要并成一步。** 拖一个节点会发几十次位置更新,一次一步的话用户得按
 *    几十下撤销才回得到上一个状态。所以攒一下再记(和自动保存同一个道理)。
 *  · **有新动作时清掉重做。** 撤回去两步、又改了点别的,那两步就再也接不上了;留着的话
 *    「重做」会把用户带到一个他从没到过的画布。
 */
export interface History {
  past: string[];
  future: string[];
  /** 当前这一份 —— 它不在 past 里,撤销时才被推进 future。 */
  present: string;
}

export function emptyHistory(present: string): History {
  return { past: [], future: [], present };
}

/** 记一步。和当前这份一样就什么也不做(比如自动保存回来的那一轮重渲染)。 */
export function record(history: History, next: string, limit = 100): History {
  if (next === history.present) return history;
  const past = [...history.past, history.present];
  return {
    // 摞太多会一直占着内存,而没人会撤销一百步以上。丢的是最老的那几步。
    past: past.length > limit ? past.slice(past.length - limit) : past,
    future: [],
    present: next,
  };
}

export function canUndo(history: History): boolean {
  return history.past.length > 0;
}

export function canRedo(history: History): boolean {
  return history.future.length > 0;
}

/** 退一步。回 null 表示没得退 —— 调用方据此不去动画布。 */
export function undo(history: History): History | null {
  if (history.past.length === 0) return null;
  const past = history.past.slice(0, -1);
  const present = history.past[history.past.length - 1];
  return { past, future: [history.present, ...history.future], present };
}

export function redo(history: History): History | null {
  if (history.future.length === 0) return null;
  const [present, ...future] = history.future;
  return { past: [...history.past, history.present], future, present };
}
