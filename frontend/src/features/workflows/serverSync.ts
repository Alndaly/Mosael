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
  /**
   * 我们自己存上去(或刚换上画布)、还没在 props 上见到的那几版,记的是**图的摘要**(graph_hash),
   * 按存的先后。
   *
   * 此前是一个布尔「下一版是我们的」:保存刚成功、它还没回来时,智能体经确认卡改了图 —— 先到的
   * 是智能体那一版,却被当成自己的认下、不重建,画布停在旧图上。比摘要才认得出到底是谁的。
   * 是一串而不是一个:连存两次,两版可能先后回来,也可能只回来后一版。
   */
  ours: readonly string[];
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
  incoming: { updatedAt: string; graphHash: string; dirty: boolean },
): { action: SyncAction; next: SyncState } {
  // 已经认过的那一版 —— effect 因为别的原因重跑时走这里,不该被当成"服务端又变了"。
  if (incoming.updatedAt === state.accounted) return { action: "skip", next: state };
  // 回来的是自己存的某一版:认下,不重建。它之前存的那几版不会再回来了(服务端已经越过它们)。
  const mine = state.ours.indexOf(incoming.graphHash);
  if (mine >= 0) return { action: "accept-ours", next: { accounted: incoming.updatedAt, ours: state.ours.slice(mine + 1) } };
  // 画布上还有没存的改动:先不盖。**也不认** —— 认了就再也不会应用它,
  // 而本地这次存完之后它才该轮到(见 dirty 变回 false 时的那一轮)。
  if (incoming.dirty) return { action: "skip", next: state };
  // 别处的改动盖上来了,我们手里等着的那几版就不会再回来。
  return { action: "apply", next: { accounted: incoming.updatedAt, ours: [] } };
}
