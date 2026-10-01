/**
 * 撤销 / 重做回到一份快照时,**服务端归属的东西补回去**(ADR 0025「撤销 / 重做与 CAS」)。
 *
 * 撤销只撤人的编辑,不撤回服务端落下的东西:在跑的一格撤不没(任务照跑、钱照花,撤成空槽的话第二份钱也花出去了),
 * 一次运行交回的产出撤不成「从没发生」,服务端新建的格子(一项能力的产出、一次多张的其余几张、智能体加的)和它们
 * 的来历线照留。和后端 run_state._keep_server_owned_state、boardItemState.serverOwnedPatch 是**同一条规矩**,
 * 两处要一起改。
 *
 * **只在「应用这一份快照」时做一次**,不去改写撤销栈里那一百份:此前每采用一次服务端的新一版,整摞快照都
 * 按它三方合并一遍(100 份 × 1000 格约一秒),而且合错 —— 本地新放、后来开跑的一格,在更早的快照里不存在,
 * 被当成「本地删掉的」,撤两步在跑的那一格就没了。
 *
 * 纯函数,不碰 React。
 */
import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { derivesOutputs } from "@/api/client";
import { itemIsRunning, itemJobId, itemRunStatus } from "@/features/boards/boardItemState";

const MEDIA_KINDS: ReadonlySet<BoardItem["kind"]> = new Set(["image", "video", "audio"]);

/** 派生落点的宿主:这一轮的产出新建在右边,它自己的字段(音频格里那段音频)归人。同后端 producer_ids.derives_outputs。 */
function derives(item: BoardItem): boolean {
  return Boolean(item.run?.ability) || derivesOutputs(item.form?.producer);
}

/** 快照里的这一格,补上此刻那一格归服务端的运行态和产出。同后端 _keep_server_owned_state 逐格的那几条。 */
function withServerState(mine: BoardItem, now: BoardItem): BoardItem {
  const derived = derives(now);
  //: 此刻在跑的是另一轮(或快照里根本不在跑):这一轮留着。
  if (itemIsRunning(now) && itemJobId(mine) !== itemJobId(now)) {
    if (derived) return { ...mine, run: now.run };
    const { asset_id: _old, ...rest } = mine;
    return { ...rest, run: now.run };
  }
  //: 一次运行交回的产出已经到了,快照里还是没有产出的那一格(撤到生成之前):产出留着。
  const output = MEDIA_KINDS.has(now.kind) && Boolean(now.asset_id) && itemRunStatus(now) === "succeeded";
  if (!derived && !mine.asset_id && output) {
    return { ...mine, asset_id: now.asset_id, run: now.run };
  }
  //: 快照里那一轮还在跑,此刻它已经落了终态:终态赢 —— 不然那一格被写回「在跑」,永远转圈。
  const waiting = itemRunStatus(mine) === "queued" || itemRunStatus(mine) === "running";
  if (waiting && !itemIsRunning(now) && now.run) {
    const settled = { ...mine, run: now.run };
    //: 便签写字的产出是正文:落下的正文和用掉的表单跟着终态一起留。
    if (itemRunStatus(now) === "succeeded" && now.kind === "note" && !derived) return { ...settled, text: now.text, form: now.form };
    return settled;
  }
  return mine;
}

/**
 * `snapshot` 是要装回去的那一份,`current` 是画布此刻,`landed` 是服务端落下、人还没亲手删过的格子(见
 * useBoardHistory.adopt)。回补好的那一份。
 */
export function withServerOwned(snapshot: Canvas, current: Canvas, landed: ReadonlySet<string>): Canvas {
  const now = new Map(current.items.map((item) => [item.id, item]));
  const there = new Set(snapshot.items.map((item) => item.id));
  const items = snapshot.items.map((item) => {
    const live = now.get(item.id);
    return live ? withServerState(item, live) : item;
  });
  //: 快照里没有的:在跑的一格、服务端落下的格子,照此刻的样子补回去。
  const back = current.items.filter((item) => !there.has(item.id) && (itemIsRunning(item) || landed.has(item.id)));
  if (back.length === 0) return { ...snapshot, items };
  const alive = new Set([...there, ...back.map((item) => item.id)]);
  const returned = new Set(back.map((item) => item.id));
  const edgeIds = new Set(snapshot.edges.map((edge) => edge.id));
  //: 补回来的格子连着的线(来历线、连进它的上游)也补回去 —— 两头都在才补,服务端不收悬空的线。
  const edges = current.edges.filter(
    (edge) =>
      !edgeIds.has(edge.id) &&
      (returned.has(edge.source) || returned.has(edge.target)) &&
      alive.has(edge.source) &&
      alive.has(edge.target),
  );
  return { ...snapshot, items: [...items, ...back], edges: [...snapshot.edges, ...edges] };
}
