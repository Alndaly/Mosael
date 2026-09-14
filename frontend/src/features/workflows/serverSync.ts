/**
 * 服务端那份图变了,要不要拿它盖掉画布上的这一份。
 *
 * 这个判断此前散在一个 effect 和两处 mutation 回调的三个 ref 里,被修过两次还在漏 ——
 * 因为它真正的输入有四个(服务端这一版是谁、我们已经认过哪一版、这一版是不是我们自己刚存的、
 * 画布脏不脏),而 effect 会因为**其中任何一个无关的重渲染**再跑一遍。收成一个纯函数,
 * 让这四个输入摆在一起,也让"自动保存之后会不会白重建一次画布"这种事能被一条用例钉住。
 *
 * 重建画布的代价不是零:它会丢掉 React Flow 量好的尺寸,节点有一帧是 visibility:hidden ——
 * 那一帧里抓节点会抓到画布上变成平移,而 @ 引用的浮层会跟着光标一起跳一下。
 */
export interface SyncState {
  /** 我们已经认过的那一版(用服务端的 updated_at 表示)。 */
  accounted: string;
  /** 下一版是我们自己刚存上去的。两端 updated_at 序列化可能不一致,所以除了比对还留这个兜底。 */
  ours: boolean;
}

export type SyncAction =
  /** 什么都不做。 */
  | "skip"
  /** 这一版是我们自己存的:认下来,但不重建画布。 */
  | "accept-ours"
  /** 别处改的:拿它盖掉画布。 */
  | "apply";

export function syncFromServer(
  state: SyncState,
  incoming: { updatedAt: string; dirty: boolean },
): { action: SyncAction; next: SyncState } {
  // 已经认过的那一版 —— effect 因为别的原因重跑时走这里,不该被当成"服务端又变了"。
  if (incoming.updatedAt === state.accounted) return { action: "skip", next: state };
  if (state.ours) return { action: "accept-ours", next: { accounted: incoming.updatedAt, ours: false } };
  // 画布上还有没存的改动:先不盖。**也不认** —— 认了就再也不会应用它,
  // 而本地这次存完之后它才该轮到(见 dirty 变回 false 时的那一轮)。
  if (incoming.dirty) return { action: "skip", next: state };
  return { action: "apply", next: { accounted: incoming.updatedAt, ours: false } };
}
