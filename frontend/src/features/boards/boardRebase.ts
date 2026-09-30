/**
 * 把本地没存上的改动**重放到服务端最新那一版上**(三方合并):画板的保存撞了版本号、轮询拿到了新的一版时都走它。
 *
 * 画板是整份快照 + base_revision 去比较并交换。服务端那一版前进了,原因多半不是「别人」:一次生成的占位、回执落下
 * 的产出、智能体改板批准后的那一步,都是服务端写的。此前一撞 409 就把本地整份换成服务端那份 —— 刚拖的、刚敲的
 * 一起没了,每出一张图就可能丢一次手上的活。
 *
 * 三份画布:`base` 是本地这些改动的底子(上一次和服务端对上的那份,confirmedCanvas),`mine` 是本地此刻,
 * `theirs` 是服务端最新。**按格子、按字段**合:
 *
 * · 本地改过的字段(和 base 不一样)用本地的;没改过的用服务端的 —— 拖了一格、它的产出同时落下,两样都在。
 * · 本地新加的格子、线、标记留着;本地删掉的,服务端那边也删掉。
 * · 服务端新加的(版本、派生出来的几格、智能体加的)留着;服务端删掉的,本地也删掉。
 * · 两边改了**同一格的同一个字段**、改得还不一样,才算冲突:用本地的(那是人眼前刚做的),并报告出来,
 *   让界面说一声。运行态和产出即便这里用了本地的,服务端保存时照样按它自己的规矩留(_keep_server_owned_state)。
 *
 * 纯函数,不碰 React。撤销栈里的每一份快照也按同一个 base / theirs 合一遍(见 useBoardHistory.adopt):
 * 撤一步回到的样子里照样有刚落下的产出。
 */
import type { BoardCanvas as Canvas } from "@/api/client";
import { sameContent } from "@/lib/optimisticWrites";

export interface Rebased {
  canvas: Canvas;
  /** 有没有两边改了同一格同一字段、改得不一样的地方(用了本地的)。 */
  conflicted: boolean;
}

type Keyed = { id: string };

/** 一格(一根线、一枚标记):服务端那份上,盖上本地相对 base 改过的字段。 */
function mergeOne<T extends Keyed>(was: T, mine: T, now: T, onConflict: () => void): T {
  const out: Record<string, unknown> = { ...now };
  const before = was as Record<string, unknown>;
  const local = mine as Record<string, unknown>;
  const theirs = now as Record<string, unknown>;
  for (const key of new Set([...Object.keys(before), ...Object.keys(local)])) {
    if (sameContent(local[key], before[key])) continue;
    if (!sameContent(theirs[key], before[key]) && !sameContent(theirs[key], local[key])) onConflict();
    if (local[key] === undefined) delete out[key];
    else out[key] = local[key];
  }
  return out as T;
}

/** 一张按 id 认的清单三方合并。顺序照本地的,服务端新加的接在后面。 */
function mergeList<T extends Keyed>(base: T[], mine: T[], theirs: T[], onConflict: () => void): T[] {
  const was = new Map(base.map((one) => [one.id, one]));
  const now = new Map(theirs.map((one) => [one.id, one]));
  const local = new Set(mine.map((one) => one.id));
  const out: T[] = [];
  for (const one of mine) {
    const before = was.get(one.id);
    const current = now.get(one.id);
    if (!before) {
      //: 本地新加的。服务端碰巧也有同一个 id(同一个人在两处加的)—— 用本地这份。
      out.push(one);
      continue;
    }
    if (!current) {
      //: 服务端那边删了。本地还改过它的话是冲突 —— 删照服务端:它多半是被别人或智能体明确删掉的。
      if (!sameContent(one, before)) onConflict();
      continue;
    }
    out.push(mergeOne(before, one, current, onConflict));
  }
  for (const one of theirs) {
    if (local.has(one.id) || was.has(one.id)) continue;
    out.push(one);
  }
  return out;
}

export function rebaseCanvas(base: Canvas, mine: Canvas, theirs: Canvas): Rebased {
  let conflicted = false;
  const onConflict = () => {
    conflicted = true;
  };
  const items = mergeList(base.items, mine.items, theirs.items, onConflict);
  const alive = new Set(items.map((item) => item.id));
  //: 线的两头有一头没了(对面删了那一格),线跟着走 —— 服务端不收悬空的线。
  const edges = mergeList(base.edges, mine.edges, theirs.edges, onConflict).filter(
    (edge) => alive.has(edge.source) && alive.has(edge.target),
  );
  const markers = mergeList(base.markers ?? [], mine.markers ?? [], theirs.markers ?? [], onConflict);
  return { canvas: { items, edges, markers }, conflicted };
}
