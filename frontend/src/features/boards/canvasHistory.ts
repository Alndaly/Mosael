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
 *
 * 时间线格(ADR 0030)里的剪刀、删除、拖动排序、连线加片段改的是**服务端的一条时间线**,不是画布:它们在这摞里记成
 * 一个「时间线的一步」,撤到它时画布不动,调那条时间线自己的撤销(用户:「剪切操作不支持撤销吗」)。一摞里交错着两种步,
 * ⌘Z 就按用户做的先后一步步退,不管那一步落在画布上还是时间线上。
 *
 * 时间线的一步记着**做完之后时间线停在第几版**(`revision`)。同一条时间线可能在剪辑页、智能体那里又被改过 ——
 * 那时服务端的「撤最新一步」撤的是别人的那一步;带着版本号去撤,不对就 409,这一步从摞里拿掉(`dropSequenceStep`)。
 * 撤 / 重做成功后,这一步的版本号换成服务端回来的那一版(`retagSequenceStep`),下一次重做 / 撤销照它比。
 */

/**
 * 时间线格里做的一步:撤销 / 重做它就是那条时间线自己的撤销 / 重做。
 *
 * `canvas`:这一步**同时改了画布**(把一格连进时间线格:画布上多一根线,时间线上多一段)—— 撤 / 重做它时画布也回到
 * 这一份。人做的是一件事,撤一下就该都回去;此前线是画布的一步、片段是时间线的一步,要按两下撤销。
 */
export type SequenceStep = { sequence: string; revision: number; canvas?: string };
/** 一步:画布的一份快照(字符串),或者时间线的一步。 */
export type Step = string | SequenceStep;

export function sequenceOf(step: Step | undefined): string | null {
  return typeof step === "object" ? step.sequence : null;
}

export interface History {
  past: Step[];
  future: Step[];
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

/** 记一步时间线上的操作(做完之后时间线在第 `revision` 版)。画布没变,present 不动;和画布的一步一样清掉重做。 */
export function recordSequence(history: History, sequenceId: string, revision: number, limit = 100): History {
  const past = [...history.past, { sequence: sequenceId, revision }];
  return { past: past.length > limit ? past.slice(past.length - limit) : past, future: [], present: history.present };
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
  const step = history.past[history.past.length - 1];
  //: 时间线的一步:画布停在原处,这一步挪进重做。连着画布的:画布回到那一份,重做时回到现在这一份。
  if (typeof step === "object") {
    if (step.canvas === undefined) return { past, future: [step, ...history.future], present: history.present };
    return { past, future: [{ ...step, canvas: history.present }, ...history.future], present: step.canvas };
  }
  return { past, future: [history.present, ...history.future], present: step };
}

export function redo(history: History): History | null {
  if (history.future.length === 0) return null;
  const [step, ...future] = history.future;
  if (typeof step === "object") {
    if (step.canvas === undefined) return { past: [...history.past, step], future, present: history.present };
    return { past: [...history.past, { ...step, canvas: history.present }], future, present: step.canvas };
  }
  return { past: [...history.past, history.present], future, present: step };
}

/** 这一步时间线的撤 / 重做做成了:它现在在 `past` 的末尾(重做之后)或 `future` 的开头(撤销之后),版本号换成回来的那一版。 */
export function retagSequenceStep(history: History, where: "past" | "future", revision: number): History {
  const index = where === "past" ? history.past.length - 1 : 0;
  const list = where === "past" ? history.past : history.future;
  const step = list[index];
  if (typeof step !== "object") return history;
  const next = [...list];
  next[index] = { ...step, revision };
  return where === "past" ? { ...history, past: next } : { ...history, future: next };
}

/** 这一步时间线撤 / 重做不成(在别处改过、撤不了):从摞里拿掉,免得下一次 ⌘Z 又撞上它。连着画布的那一步只拿掉时间线
 *  那一半 —— 画布已经回去了,它退回成画布的一步,还撤得回、重做得回。 */
export function dropSequenceStep(history: History, where: "past" | "future"): History {
  const list = where === "past" ? history.past : history.future;
  const index = where === "past" ? list.length - 1 : 0;
  const step = list[index];
  if (typeof step !== "object") return history;
  const next = step.canvas === undefined ? list.filter((_, at) => at !== index) : list.map((one, at) => (at === index ? (step.canvas as string) : one));
  return where === "past" ? { ...history, past: next } : { ...history, future: next };
}

/**
 * 把画布上刚记下的那一步(连了一根线进时间线格)和时间线上随之做成的那一步并成一步(见 SequenceStep.canvas)。
 * 只在对得上时并:眼前的画布有这根线、上一份没有 —— 中间人又做了别的,就不并,各记各的。并不上回 null。
 */
export function joinSequenceToCanvas(
  history: History,
  sequenceId: string,
  revision: number,
  link: { source: string; target: string },
): History | null {
  const last = history.past.at(-1);
  if (typeof last !== "string") return null;
  const linked = (snapshot: string) =>
    (JSON.parse(snapshot) as { edges?: { source: string; target: string }[] }).edges?.some(
      (edge) => edge.source === link.source && edge.target === link.target,
    ) ?? false;
  if (!linked(history.present) || linked(last)) return null;
  return { ...history, past: [...history.past.slice(0, -1), { sequence: sequenceId, revision, canvas: last }] };
}
