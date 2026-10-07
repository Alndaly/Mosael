/**
 * 在这张画布上点的**一次运行**落下了什么 —— 撤销里它是一步(canvasHistory 的 RunStep),撤它就把这一轮放上画布的东西
 * 整份拿下来,重做再放回去。
 *
 * 运行是异步的:点下去的那一刻只有一步空的记号,占位、产出由服务端在之后的某一版里落下(回执、轮询采用的那一版)。
 * 所以每采用一版服务端的画布,就把新落下的格子认给还没收尾的那几轮(`claimLanding`);收尾时记下宿主那一格的样子。
 * 认的依据都是服务端写死的事实,不猜:
 *
 *  · 这一轮跑的就是这一格(`host`):截一段落成的新格子,id 就是请求里的那个;
 *  · 带着这一轮任务号在跑的格子:一次出几张时一起摆好的占位(outputs.sibling_placeholders);
 *  · 从宿主连出来的新格子:一项能力 / 派生产出新建在右边,连一根来历线(outputs._derive)。
 *
 * 认不出的(一次多张、当场就跑完时多出来的那几张)照旧当「服务端落下的」,撤销不碰它们 —— 宁可少撤,不撤错。
 *
 * **撤不了还在跑的那一轮**(ADR 0025):任务照跑、钱照花,撤成空槽的话第二份钱也花出去了。收尾之前那一步撤不动
 * (useBoardHistory 说一声),收尾之后整份撤得掉 —— 素材、笔记还在各自的库里,画布上拿下来而已。
 *
 * 纯函数,不碰 React。
 */
import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { derivesOutputs } from "@/api/client";
import { itemIsRunning, itemJobId } from "@/features/boards/boardItemState";

type CanvasEdge = Canvas["edges"][number];

export type BoardRun = {
  /** 跑的那一格(请求里的 item_id)。 */
  host: string;
  /** 这一轮的任务号:宿主第一次带着它在跑时认下。当场就跑完的一轮没有。 */
  job?: string;
  /** 请求回来了(占位摆下了,或者当场就跑完了)。 */
  placed: boolean;
  /** 这一轮收尾了:产出落下、跑挂了、被取消。收尾之前撤不动它。 */
  landed: boolean;
  /** 这一轮新建的格子,服务端最近的那一版 —— 撤掉之后再重做,画布上已经没有它们了,从这里放回去。 */
  items: Map<string, BoardItem>;
  /** 连着这几格的线(来历线)。 */
  edges: Map<string, CanvasEdge>;
  /** 收尾时宿主那一格的样子(就地填进来的产出、终态)。 */
  fill?: BoardItem;
  /** 这一轮还在跑时记下的那几份画布(这一步之后、收尾之前):装回它们时产出还没落下,得补上(见 boardServerOwned)。 */
  inFlight: Set<string>;
};

export function newRun(host: string): BoardRun {
  return { host, placed: false, landed: false, items: new Map(), edges: new Map(), inFlight: new Set() };
}

/** 这一格此刻在跑的任务号(排队或运行中)。 */
function liveJob(item: BoardItem | undefined): string | undefined {
  return item && itemIsRunning(item) ? itemJobId(item) : undefined;
}

/** 收尾:记下宿主此刻的样子。 */
function land(run: BoardRun, host: BoardItem | undefined) {
  run.landed = true;
  run.fill = host;
}

/**
 * 采用服务端的一版(`adopted`)时:把新落下的格子(`before` 里没有的)认给还没收尾的那几轮,已经认下的换成这一版,
 * 宿主不再跑这一轮的任务就收尾。回这一次认走的格子 id —— 它们不是「服务端自己落下的」(见 useBoardHistory 的 landed)。
 * 就地修改 `runs` 里的记录。
 */
export function claimLanding(runs: Iterable<BoardRun>, before: ReadonlyMap<string, BoardItem>, adopted: Canvas): Set<string> {
  const byId = new Map(adopted.items.map((item) => [item.id, item]));
  const fresh = adopted.items.filter((item) => !before.has(item.id));
  const claimed = new Set<string>();
  for (const run of runs) {
    if (run.landed) continue;
    const host = byId.get(run.host);
    run.job ??= liveJob(host);
    const fromHost = new Set(adopted.edges.filter((edge) => edge.source === run.host).map((edge) => edge.target));
    for (const item of fresh) {
      if (claimed.has(item.id)) continue;
      if (item.id === run.host || (run.job && liveJob(item) === run.job) || fromHost.has(item.id)) {
        run.items.set(item.id, item);
        claimed.add(item.id);
      }
    }
    for (const id of run.items.keys()) {
      const now = byId.get(id);
      if (now) run.items.set(id, now);
    }
    for (const edge of adopted.edges) {
      if (run.items.has(edge.source) || run.items.has(edge.target)) run.edges.set(edge.id, edge);
    }
    //: 认过任务号而宿主不再跑它(落下了、跑挂了、被取消、整格被删);或请求回来了、却从没见它跑过(当场就跑完了)。
    if ((run.job && liveJob(host) !== run.job) || (run.placed && !run.job && !liveJob(host))) land(run, host);
  }
  return claimed;
}

/**
 * 请求回来了:`placed` 是服务端回的那一版里的宿主,`local` 是画布此刻的宿主(回的那一版可能已经被更新的一版盖过 ——
 * 轮询先采用了更新的,这一版就不采用)。认下任务号;宿主此刻不在跑这一轮就收尾。
 */
export function placeRun(run: BoardRun, placed: BoardItem | undefined, local: BoardItem | undefined): void {
  run.placed = true;
  run.job ??= liveJob(placed);
  if (!run.landed && (!run.job || liveJob(local) !== run.job)) land(run, local);
}

/** 这一轮放上画布的产出有几份、有没有素材(撤掉它时说一声:「撤下了几份,素材库里还在」)。 */
export function runOutputs(run: BoardRun): { count: number; assets: boolean } {
  const cells = [...run.items.values()];
  const fill = run.fill;
  //: 就地填进宿主的那一份:派生落点的宿主自己的内容不是这一轮的产出。
  const filled = fill && !fill.run?.ability && !derivesOutputs(fill.form?.producer) && fill.run?.status === "succeeded";
  const assets = cells.some((one) => one.asset_id) || Boolean(filled && fill.asset_id);
  return { count: cells.length + (filled ? 1 : 0), assets };
}
