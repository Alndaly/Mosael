/**
 * 撤销 / 重做回到一份快照时,**服务端归属的东西补回去**(ADR 0025「撤销 / 重做与 CAS」)。
 *
 * 在跑的一格撤不没(任务照跑、钱照花,撤成空槽的话第二份钱也花出去了);**不是这一摞里哪一步引起的**服务端落下的
 * 东西(智能体加的格子、别处或打开这张板之前点的运行交回的产出)照留,连同它们的来历线 —— 它们不是这个人在这里做的
 * 哪一件事,撤销撤不到它们。和后端 run_state._keep_server_owned_state、boardItemState.serverOwnedPatch 是**同一条
 * 规矩**,两处要一起改。
 *
 * **在这张画布上点的运行**是撤销里的一步(canvasHistory 的 RunStep,落下了什么见 boardRuns):撤到它之前,这一轮新建的
 * 格子拿下来、就地填进宿主的产出不补回(`undone`);装回它还在跑时记下的一份,落下的产出照落下的那一版补上(`inFlight`)。
 * 素材、笔记还在各自的库里,画布上拿下来而已。
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
import type { BoardRun } from "@/features/boards/boardRuns";

const MEDIA_KINDS: ReadonlySet<BoardItem["kind"]> = new Set(["image", "video", "audio"]);

/** 派生落点的宿主:这一轮的产出新建在右边,它自己的字段(音频格里那段音频)归人。同后端 producer_ids.derives_outputs。 */
function derives(item: BoardItem): boolean {
  return Boolean(item.run?.ability) || derivesOutputs(item.form?.producer);
}

/**
 * 快照里的这一格,补上此刻那一格归服务端的运行态和产出。同后端 _keep_server_owned_state 逐格的那几条。
 * `keepOutput`:撤掉的那一轮的宿主不补它交回的产出 —— 撤的就是它。
 */
function withServerState(mine: BoardItem, now: BoardItem, keepOutput = true): BoardItem {
  const derived = derives(now);
  //: 此刻在跑的是另一轮(或快照里根本不在跑):这一轮留着。
  if (itemIsRunning(now) && itemJobId(mine) !== itemJobId(now)) {
    if (derived) return { ...mine, run: now.run };
    const { asset_id: _old, ...rest } = mine;
    return { ...rest, run: now.run };
  }
  if (!keepOutput) return mine;
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
 * 宿主在一份「这一轮还在跑」的快照里,照服务端摆占位那样看:在跑这一轮,就地的旧产出让位(派生落点的宿主不让 ——
 * 它自己的内容不是产出)。点下去到请求回来之间记下的那份里宿主还没摆占位,也按摆了算,好让落下的那一版接得上。
 */
function asPlaced(mine: BoardItem, job: string | undefined): BoardItem {
  if (itemIsRunning(mine) && itemJobId(mine) === job) return mine;
  const { asset_id: _old, ...rest } = mine;
  return { ...(derives(mine) ? mine : rest), run: { status: "running", ...(job ? { job_id: job } : {}) } };
}

/** 撤 / 重做到一份快照时那几次运行的处境(见文件开头)。 */
export type RunsInPlay = {
  /** 这一步被撤掉了(在 future 里)的那几轮。 */
  undone: readonly BoardRun[];
  /** 这一步还在效、已经收尾,而这份快照记在它还在跑时的那几轮。 */
  inFlight: readonly BoardRun[];
};
const NO_RUNS: RunsInPlay = { undone: [], inFlight: [] };

/**
 * `snapshot` 是要装回去的那一份,`current` 是画布此刻,`landed` 是服务端落下、人还没亲手删过、也不是这一摞里哪一步
 * 引起的格子(见 useBoardHistory.adopt),`runs` 是这一摞里那几次运行的处境。回补好的那一份。
 */
export function withServerOwned(snapshot: Canvas, current: Canvas, landed: ReadonlySet<string>, runs: RunsInPlay = NO_RUNS): Canvas {
  const now = new Map(current.items.map((item) => [item.id, item]));
  //: 撤掉的那几轮:新建的格子不补(它们不在 `landed` 里 —— 是这一摞里那一步的,不是服务端自己落下的),宿主就地的产出也不补。
  const bare = new Set(runs.undone.map((run) => run.host));
  //: 还在跑时记下的那份:这一轮的格子和宿主,照落下的那一版补。
  const landing = new Map<string, { run: BoardRun; item: BoardItem }>();
  for (const run of runs.inFlight) {
    for (const [id, item] of run.items) landing.set(id, { run, item });
    if (run.fill && !run.items.has(run.host)) landing.set(run.host, { run, item: run.fill });
  }
  const there = new Set(snapshot.items.map((item) => item.id));
  const items = snapshot.items.map((item) => {
    const settled = landing.get(item.id);
    if (settled) return withServerState(asPlaced(item, settled.run.job), settled.item);
    const live = now.get(item.id);
    return live ? withServerState(item, live, !bare.has(item.id)) : item;
  });
  //: 快照里没有的:在跑的一格、服务端落下的格子(照此刻的样子),还在跑时记下的那份里还没落下的这一轮的格子(照落下的那一版)。
  const back = [
    ...current.items.filter((item) => !there.has(item.id) && !landing.has(item.id) && (itemIsRunning(item) || landed.has(item.id))),
    ...runs.inFlight.flatMap((run) => [...run.items.values()].filter((item) => !there.has(item.id))),
  ];
  if (back.length === 0) return { ...snapshot, items };
  const alive = new Set([...there, ...back.map((item) => item.id)]);
  const returned = new Set(back.map((item) => item.id));
  const edgeIds = new Set(snapshot.edges.map((edge) => edge.id));
  //: 补回来的格子连着的线(来历线、连进它的上游)也补回去 —— 两头都在才补,服务端不收悬空的线。
  const edges = [...current.edges, ...runs.inFlight.flatMap((run) => [...run.edges.values()])].filter((edge) => {
    if (edgeIds.has(edge.id)) return false;
    if (!(returned.has(edge.source) || returned.has(edge.target)) || !alive.has(edge.source) || !alive.has(edge.target)) return false;
    edgeIds.add(edge.id);
    return true;
  });
  return { ...snapshot, items: [...items, ...back], edges: [...snapshot.edges, ...edges] };
}
