/**
 * 撤 / 重做回到一份快照时服务端归属的东西怎么补(boardServerOwned):在跑的、不是这一摞里哪一步引起的落下照留;
 * 这一摞里的运行照它那一步在不在效 —— 撤掉的整份拿下,还在跑时记下的那份照落下的那一版补上。
 */
import { describe, expect, it } from "vitest";

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { newRun, type BoardRun } from "./boardRuns";
import { withServerOwned } from "./boardServerOwned";

const image = (id: string, extra: Partial<BoardItem> = {}): BoardItem => ({ id, kind: "image", x: 0, y: 0, width: 260, height: 180, ...extra });
const canvas = (items: BoardItem[], edges: Canvas["edges"] = []): Canvas => ({ items, edges, markers: [] });
const ids = (one: Canvas) => one.items.map((item) => item.id);

function landedRun(host: string, items: BoardItem[], fill: BoardItem, job = "job-1"): BoardRun {
  const run = newRun(host);
  run.job = job;
  run.placed = true;
  run.landed = true;
  run.fill = fill;
  for (const item of items) run.items.set(item.id, item);
  for (const item of items) run.edges.set(`${host}->${item.id}`, { id: `${host}->${item.id}`, source: host, target: item.id });
  return run;
}

describe("撤到一次运行之前", () => {
  const host = image("qr", { asset_id: "a" });
  const tiles = [image("qr-out-1", { asset_id: "t1" }), image("qr-out-2", { asset_id: "t2" })];
  const settled = { ...host, run: { status: "succeeded" as const, ability: "node:image_grid_split" as const } };
  const now = canvas([settled, ...tiles], tiles.map((one) => ({ id: `qr->${one.id}`, source: "qr", target: one.id })));

  it("这一轮新建的格子和它们的来历线拿下来,宿主回到点之前 —— 不像服务端落下的那样一律补回", () => {
    const run = landedRun("qr", tiles, settled);
    const back = withServerOwned(canvas([host]), now, new Set(), { undone: [run], inFlight: [] });
    expect(ids(back)).toEqual(["qr"]);
    expect(back.edges).toEqual([]);
    expect(back.items[0].run, "宿主回到点之前的样子").toBeUndefined();
  });

  it("就地填进宿主的产出不补回(撤的就是它);撤别的步时照旧补回", () => {
    const slot = image("s", { form: { producer: "generate", prompt: "猫" } });
    const filled = { ...slot, asset_id: "made", run: { status: "succeeded" as const } };
    const run = landedRun("s", [], filled);
    const undone = withServerOwned(canvas([slot]), canvas([filled]), new Set(), { undone: [run], inFlight: [] });
    expect(undone.items[0].asset_id).toBeUndefined();
    expect(undone.items[0].form?.prompt, "提示词回来了,改一改可以再来").toBe("猫");
    const other = withServerOwned(canvas([slot]), canvas([filled]), new Set());
    expect(other.items[0].asset_id, "不是这一摞里的运行(别处点的):照旧补回").toBe("made");
  });

  it("不是这一摞里哪一步引起的落下(智能体加的)照留,在跑的一格照留", () => {
    const run = landedRun("qr", tiles, settled);
    const agent = image("agent");
    const busy = image("busy", { run: { status: "running", job_id: "j" } });
    const back = withServerOwned(canvas([host]), canvas([...now.items, agent, busy]), new Set(["agent"]), { undone: [run], inFlight: [] });
    expect(ids(back).sort()).toEqual(["agent", "busy", "qr"]);
  });
});

describe("装回一份这一轮还在跑时记下的快照", () => {
  it("落下的格子照落下的那一版补上 —— 哪怕撤过又重做、画布上一时没有它们;宿主照落下的终态", () => {
    const host = image("qr", { asset_id: "a" });
    const tiles = [image("qr-out-1", { asset_id: "t1", x: 400 })];
    const settled = { ...host, run: { status: "succeeded" as const, ability: "node:image_grid_split" as const } };
    const run = landedRun("qr", tiles, settled);
    const midway = canvas([{ ...host, run: { status: "running", job_id: "job-1", ability: "node:image_grid_split" as const } }, image("note")]);
    const back = withServerOwned(midway, canvas([host]), new Set(), { undone: [], inFlight: [run] });
    expect(ids(back)).toEqual(["qr", "note", "qr-out-1"]);
    expect(back.items[0].run).toEqual(settled.run);
    expect(back.edges.map((one) => one.id)).toEqual(["qr->qr-out-1"]);
  });

  it("就地生成:快照里在等这一轮的那一格换上落下的产出;点下去到请求回来之间记下的那份(还没摆占位)也接得上", () => {
    const slot = image("s", { form: { producer: "generate", prompt: "猫" } });
    const filled = { ...slot, asset_id: "made", run: { status: "succeeded" as const } };
    const run = landedRun("s", [], filled);
    const waiting = withServerOwned(canvas([{ ...slot, run: { status: "running", job_id: "job-1" } }]), canvas([slot]), new Set(), { undone: [], inFlight: [run] });
    expect(waiting.items[0]).toMatchObject({ asset_id: "made", run: { status: "succeeded" } });
    const unplaced = withServerOwned(canvas([slot]), canvas([slot]), new Set(), { undone: [], inFlight: [run] });
    expect(unplaced.items[0]).toMatchObject({ asset_id: "made", run: { status: "succeeded" } });
  });
});
