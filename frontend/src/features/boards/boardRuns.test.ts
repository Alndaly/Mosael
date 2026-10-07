/**
 * 一次运行落下了什么(撤销里它是一步):认格子只认服务端写死的事实 —— 跑的就是那一格、带着这一轮的任务号、
 * 从宿主连出来的来历线;认不出的不认(宁可少撤,不撤错)。
 */
import { describe, expect, it } from "vitest";

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { claimLanding, newRun, placeRun, runOutputs } from "./boardRuns";

const image = (id: string, extra: Partial<BoardItem> = {}): BoardItem => ({ id, kind: "image", x: 0, y: 0, width: 260, height: 180, ...extra });
const running = (job: string, extra: Record<string, unknown> = {}) => ({ run: { status: "running" as const, job_id: job, ...extra } });
const before = (...items: BoardItem[]) => new Map(items.map((item) => [item.id, item]));
const canvas = (items: BoardItem[], edges: Canvas["edges"] = []): Canvas => ({ items, edges, markers: [] });

describe("认下一轮落下的格子", () => {
  it("宫格切分:先认任务号,收尾那一版里从宿主连出来的九格都是它的,宿主的终态记下", () => {
    const host = image("qr", { asset_id: "a" });
    const run = newRun("qr");
    claimLanding([run], before(host), canvas([{ ...host, ...running("job-1", { ability: "node:image_grid_split" as const }) }]));
    expect(run.job).toBe("job-1");
    expect(run.landed).toBe(false);

    const tiles = Array.from({ length: 9 }, (_, i) => image(`qr-out-${i + 1}`, { asset_id: `t${i}` }));
    const settled = { ...host, run: { status: "succeeded" as const, ability: "node:image_grid_split" as const } };
    const claimed = claimLanding([run], before({ ...host, ...running("job-1") }), canvas([settled, ...tiles], tiles.map((one) => ({ id: `qr->${one.id}`, source: "qr", target: one.id }))));
    expect([...claimed].sort()).toEqual(tiles.map((one) => one.id).sort());
    expect(run.landed).toBe(true);
    expect(run.fill).toEqual(settled);
    expect(run.edges.size).toBe(9);
    expect(runOutputs(run), "宿主就地没有产出(派生落点),九格都是素材").toEqual({ count: 9, assets: true });
  });

  it("一次出几张:带着这一轮任务号的占位是它的;落下之后收下的是服务端那一版", () => {
    const slot = image("s", { form: { producer: "generate", prompt: "猫" } });
    const run = newRun("s");
    claimLanding([run], before(slot), canvas([{ ...slot, ...running("job-2") }, image("s-2", running("job-2"))]));
    expect([...run.items.keys()]).toEqual(["s-2"]);
    claimLanding([run], before({ ...slot, ...running("job-2") }, image("s-2", running("job-2"))), canvas([
      { ...slot, asset_id: "a1", run: { status: "succeeded" } },
      image("s-2", { asset_id: "a2", run: { status: "succeeded" } }),
    ]));
    expect(run.landed).toBe(true);
    expect(run.items.get("s-2")?.asset_id).toBe("a2");
    expect(runOutputs(run), "就地填进宿主的那一份也算").toEqual({ count: 2, assets: true });
  });

  it("截一段:新的那一格就是这一轮跑的那一格", () => {
    const run = newRun("video-new");
    claimLanding([run], before(), canvas([{ id: "video-new", kind: "video", x: 0, y: 0, ...running("job-3") }]));
    expect([...run.items.keys()]).toEqual(["video-new"]);
  });

  it("不认:别人加的、没连着宿主的新格子;已经收尾的那一轮;一格只认给一轮", () => {
    const host = image("h", { asset_id: "a" });
    const run = newRun("h");
    const other = newRun("h2");
    const claimed = claimLanding([run, other], before(host, image("h2")), canvas([
      { ...host, ...running("job-4") },
      { ...image("h2"), ...running("job-5") },
      image("agent"),
    ]));
    expect(claimed.has("agent"), "智能体加的、谁也不连的格子不是哪一轮的").toBe(false);
    run.landed = true;
    const late = claimLanding([run], before(host), canvas([host, image("h-out-1")], [{ id: "e", source: "h", target: "h-out-1" }]));
    expect(late.size, "收了尾的那一轮不再认").toBe(0);
  });

  it("请求回来时:回的那一版里宿主在跑就认任务号;宿主此刻已经不跑了(当场就跑完、或已经被更新的一版盖过)就收尾", () => {
    const fast = newRun("h");
    placeRun(fast, image("h", { run: { status: "succeeded" } }), image("h", { run: { status: "succeeded" } }));
    expect(fast.landed).toBe(true);

    const slow = newRun("h");
    placeRun(slow, image("h", running("job-6")), image("h", running("job-6")));
    expect(slow).toMatchObject({ placed: true, job: "job-6", landed: false });

    const overtaken = newRun("h");
    placeRun(overtaken, image("h", running("job-7")), image("h", { asset_id: "made", run: { status: "succeeded" } }));
    expect(overtaken.landed, "轮询先采用了收尾的那一版:不再等一个不会来的收尾").toBe(true);
  });

  it("宿主整格没了(别处删了):收尾,不一直挡着撤销", () => {
    const run = newRun("h");
    run.job = "job-8";
    claimLanding([run], before(image("h", running("job-8"))), canvas([]));
    expect(run.landed).toBe(true);
  });
});
