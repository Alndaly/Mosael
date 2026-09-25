import type { BoardItem } from "@/api/client";

export type BoardItemRunStatus = NonNullable<BoardItem["run"]>["status"];

export function itemJobId(item: BoardItem): string | undefined {
  return item.run?.job_id;
}

export function itemError(item: BoardItem): string | undefined {
  return item.run?.error;
}

/** 所有画布节点共用的六态解释。 */
export function itemRunStatus(item: BoardItem): BoardItemRunStatus {
  return item.run?.status ?? "idle";
}

export function itemIsRunning(item: BoardItem): boolean {
  const status = itemRunStatus(item);
  // 轮询必须有可查询的 job；显式状态仍可用于节点视觉，但不能凭一个缺失 job_id 的脏快照
  // 启动永远无法收敛的 polling。
  return Boolean(itemJobId(item)) && (status === "queued" || status === "running");
}

export function runningState(jobId: string): NonNullable<BoardItem["run"]> {
  return { status: "running", job_id: jobId };
}

/**
 * 复制出来的一格。**进行中的运行态只属于原件**:任务的回执认的是原件那一格(见后端
 * receipt_to_item),便签写作回来的也只落在原件上 —— 带着「在跑」过去的副本永远等不到结束,
 * 框里一直转圈,面板一直按不动。副本退回空槽,表单(提示词、参数)照带,想要的话再点一次;
 * 已经结束的状态(有产出、失败原因)照样带过去。和后端「创建副本」是同一条规则。
 */
export function copiedItem(item: BoardItem, id: string): BoardItem {
  const status = itemRunStatus(item);
  if (status !== "queued" && status !== "running") return { ...item, id };
  const { run: _live, ...rest } = item;
  return { ...rest, id };
}

/**
 * 存回去之后,服务端留下的**运行态和产出**和本地送出去的不一样时,本地那一格该改成什么。
 *
 * 这两样归服务端(见后端 _keep_server_owned_state):客户端的快照改不动在跑的任务、抹不掉已经
 * 到了的产出。服务端没收下本地那一份时,本地要跟着回来 —— 否则撤销后的那一格看着是个能点的
 * 空槽,任务其实还在跑。只动这两样:位置、表单、文字是用户的,请求在路上时他可能又改了。
 */
export function serverOwnedPatch(sent: BoardItem, stored: BoardItem): Partial<BoardItem> | null {
  const same = JSON.stringify(sent.run ?? null) === JSON.stringify(stored.run ?? null) && sent.asset_id === stored.asset_id;
  return same ? null : { run: stored.run, asset_id: stored.asset_id };
}

/**
 * 服务端轮询到的这一格已经不在跑了:写回本地节点的补丁。成功必须连同服务端已重置的 form 一起落下。
 *
 * **按状态认「跑完了」,不按有没有失败原因。** 原因可以没有(任务失败时没留下话、被取消),
 * 此前按原因认,服务端只好拿状态名顶一个原因上去,格子上的失败原因于是写着「succeeded」。
 * 还在跑就回 null。
 */
export function boardSettlementPatch(item: BoardItem): Partial<BoardItem> | null {
  if (itemIsRunning(item)) return null;
  if (item.asset_id) {
    return {
      asset_id: item.asset_id,
      form: item.form,
      run: item.run ?? { status: "succeeded" },
    };
  }
  return { run: item.run };
}

/**
 * Composer 的局部交互状态只在“节点拿到一份新产物”时重建。
 *
 * 不能把整个 item/form stringify 进 key：每敲一个字、拖一下节点都会 remount，光标与手动选择
 * 立刻丢失。失败/取消也不换 key，输入要留给重试；成功产生新 asset、或手动换素材，才说明
 * 上一次编辑周期已经结束。持久表单本身仍在节点上，重建后从它重新水合。
 */
export function itemFormResetKey(item: BoardItem): string {
  const completed = item.run?.status === "succeeded" ? "completed" : "draft";
  return `${item.id}:${item.asset_id ?? "empty"}:${completed}`;
}
