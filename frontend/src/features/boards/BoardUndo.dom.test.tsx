/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Edge, Node } from "@xyflow/react";

/**
 * 画板撤销的一步 = 人做的一件事(useBoardHistory 开头那几条)。画布是真的,服务端换成几行照它做事的桩:
 * 摆占位(在跑、带任务号)、交回产出(宫格切分的九格 + 来历线、就地填进空槽的一张图)、轮询拿到的一版。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));
const toastMock = vi.hoisted(() => Object.assign(vi.fn(), { message: vi.fn(), error: vi.fn(), success: vi.fn(), info: vi.fn() }));
vi.mock("sonner", () => ({ toast: toastMock }));

import type { Board, BoardCanvas as Canvas, BoardItem, BoardProducerInfo, BoardRunRequest } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";
import { rebaseCanvas } from "@/features/boards/boardRebase";
import { toNodes } from "@/features/boards/boardCanvasModel";
import { useBoardHistory } from "@/features/boards/useBoardHistory";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  globalThis.fetch = vi.fn(async () => new Response("[]", { status: 200, headers: { "content-type": "application/json" } })) as never;
  Object.values(toastMock).forEach((one) => typeof one === "function" && "mockReset" in one && (one as ReturnType<typeof vi.fn>).mockReset());
  toastMock.mockReset();
});
afterEach(() => vi.useRealTimers());

const producer = (id: string, label: string, extra: Partial<BoardProducerInfo>): BoardProducerInfo =>
  ({
    id, type: id.replace(/^node:/, ""), label, description: "", category: "", config: {}, outputs: [], output_types: {},
    output_labels: {}, plugin_name: "", tool_name: "", body_scope: {}, hosts: [], role: "slot", host_fields: {},
    permission: "edit", effects: "none", fills_empty_slot: false, board_group: "", board_group_label: "",
    board_description: label, ...extra,
  }) as BoardProducerInfo;
const SPLIT = producer("node:image_grid_split", "宫格切分", {
  hosts: ["image"], role: "ability", host_fields: { image: "asset_id" },
  config: {
    asset_id: { type: "template", required: true, label: "asset_id", board_sources: ["image"] },
    grid: { type: "string", required: true, options: ["3x3", "2x2"], default: "3x3", label: "grid", board_sources: [] },
  },
});
//: 一项要接上游一段字的能力:面板一挂上就把连进来的那张便签默认接上(AbilityComposer 的默认绑定)。
const CAPTION = producer("node:x.caption", "配文", {
  hosts: ["image"], role: "ability", host_fields: { image: "asset_id" },
  config: {
    asset_id: { type: "template", required: true, label: "asset_id", board_sources: ["image"] },
    script: { type: "template", required: true, label: "script", board_sources: ["note"] },
  },
});
//: 空的图片格的一种填法(插件的生成器):产出就地填进这一格。
const PAINT = producer("node:x.paint", "画图", { hosts: ["image"], role: "slot", fills_empty_slot: true });

const image = (id: string, extra: Partial<BoardItem> = {}): BoardItem => ({ id, kind: "image", x: 0, y: 0, width: 260, height: 340, ...extra });
const note = (id: string, text: string, extra: Partial<BoardItem> = {}): BoardItem =>
  ({ id, kind: "note", x: 0, y: 400, width: 220, height: 140, color: "yellow", text, ...extra });

/**
 * 画布 + 一个照它做事的服务端。`run` 照 BoardsView.run 的样子:先把画布汇出来,服务端摆好占位(在跑、带任务号),
 * 合进本地、交回那一版。`land` 是回执落下之后轮询拿到的那一版。
 */
function mount(
  items: BoardItem[],
  { edges = [] as Canvas["edges"], producers = [SPLIT], refuse = false, onPickAsset = (() => undefined) as React.ComponentProps<typeof BoardCanvas>["onPickAsset"] } = {},
) {
  let api: BoardCanvasApi | null = null;
  const changes: Canvas[] = [];
  const server = { confirmed: { items, edges, markers: [] } as Canvas, job: 0 };
  /** 服务端的新一版合进本地(BoardsView.adoptServer 那样)。 */
  const adoptServer = (fresh: Canvas) => {
    const mine = api!.flush();
    const base = server.confirmed;
    api!.adopt(rebaseCanvas(base, mine, fresh).canvas, { base, fresh });
    server.confirmed = fresh;
  };
  const onRun = vi.fn(async (request: BoardRunRequest): Promise<Board | null> => {
    const mine = api!.flush();
    if (refuse) return null;
    //: 跑之前先把画布存上(BoardsView.run 也是):服务端照着这一份摆占位。
    server.confirmed = mine;
    server.job += 1;
    const ability = request.producer.startsWith("node:") && producers.find((one) => one.id === request.producer)?.role === "ability";
    const placed: Canvas = {
      ...mine,
      items: mine.items.map((one) =>
        one.id === request.item_id
          ? { ...one, run: { status: "running", job_id: `job-${server.job}`, ...(ability ? { ability: request.producer as `node:${string}` } : {}) } }
          : one,
      ),
    };
    adoptServer(placed);
    return { canvas: placed } as Board;
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ImagePreviewProvider>
        <div style={{ width: 800, height: 600 }}>
          <BoardCanvas boardId="b1" workspaceId="w1" canvas={server.confirmed} onChange={(next) => changes.push(next)} onPickAsset={onPickAsset}
            onRun={onRun} producers={producers} onReady={(next) => (api = next)} />
        </div>
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  const latest = () => changes.at(-1) ?? server.confirmed;
  /** 宫格切分的回执:宿主收尾,右边九格、每格一根来历线。 */
  const landTiles = (host: string, count = 9) => {
    const tiles = Array.from({ length: count }, (_, i) => image(`${host}-out-${i + 1}`, { x: 340 + (i % 3) * 224, y: Math.floor(i / 3) * 300, width: 200, height: 260, asset_id: `tile-${i}` }));
    const base = server.confirmed;
    adoptServer({
      ...base,
      items: [...base.items.map((one) => (one.id === host ? { ...one, run: { status: "succeeded" as const, ability: "node:image_grid_split" as const } } : one)), ...tiles],
      edges: [...base.edges, ...tiles.map((one) => ({ id: `${host}->${one.id}`, source: host, target: one.id }))],
    });
  };
  /** 就地填:那一格收下一张图。 */
  const landFill = (slot: string, assetId: string) => {
    const base = server.confirmed;
    adoptServer({ ...base, items: base.items.map((one) => (one.id === slot ? { ...one, asset_id: assetId, run: { status: "succeeded" as const } } : one)) });
  };
  return { api: () => api as unknown as BoardCanvasApi, latest, changes, server, adoptServer, landTiles, landFill, onRun };
}

const settle = (ms = 500) => act(async () => {
  await vi.advanceTimersByTimeAsync(ms);
});
const ids = (canvas: Canvas) => canvas.items.map((one) => one.id);
const node = (id: string) => document.querySelector<HTMLElement>(`[data-id="${id}"]`)!;
const select = (id: string) => act(() => void node(id).dispatchEvent(new MouseEvent("click", { bubbles: true })));
const key = (letter: string, shift = false) =>
  act(() => void fireEvent.keyDown(document.body, { key: letter, metaKey: true, shiftKey: shift }));
const undoKey = () => key("z");
const redoKey = () => key("z", true);
async function split(host: string) {
  select(host);
  act(() => document.querySelector<HTMLButtonElement>(`[data-board-abilities] button[aria-label="宫格切分"]`)!.click());
  await settle();
  await act(async () => {
    document.querySelector<HTMLButtonElement>("[data-board-composer-send]")!.click();
    await vi.advanceTimersByTimeAsync(10);
  });
  await settle();
}

describe("宫格切分的撤销(用户截图:切成九格之后按撤销)", () => {
  it("按一下 ⌘Z,九格连同来历线一起拿下,原图留着、还选着、面板还开着,说一声素材库里还在;⌘⇧Z 放回;再撤才撤到放上原图", async () => {
    const view = mount([]);
    act(() => void view.api().add("image", image("qr", { asset_id: "a-qr" })));
    await settle();
    await split("qr");
    act(() => view.landTiles("qr"));
    await settle();
    expect(ids(view.latest())).toHaveLength(10);

    await undoKey();
    await settle();
    expect(ids(view.latest()), "一下就把九格都拿下,原图在").toEqual(["qr"]);
    expect(view.latest().edges, "来历线一起走,不留悬空的线").toEqual([]);
    expect(view.latest().items[0].run, "原图回到点之前").toBeUndefined();
    expect(toastMock.message).toHaveBeenCalledWith("boardUndoRunAssets");
    expect(node("qr").classList.contains("selected"), "撤销不取消选中").toBe(true);
    expect(document.querySelector("[data-board-composer]"), "宫格切分的面板还开着,可以换个宫格再切").not.toBeNull();

    await redoKey();
    await settle();
    expect(ids(view.latest())).toHaveLength(10);
    expect(view.latest().edges).toHaveLength(9);

    await undoKey();
    await undoKey();
    await settle();
    expect(ids(view.latest()), "第二下撤的才是放上原图").toEqual([]);
    expect(view.api().canUndo).toBe(false);
  });

  it("还在跑的那一轮撤不动:说一声,画布不动;落下之后一下撤掉", async () => {
    const view = mount([image("qr", { asset_id: "a-qr" })]);
    await split("qr");
    expect(view.latest().items[0].run?.status).toBe("running");
    await undoKey();
    await settle();
    expect(toastMock.message).toHaveBeenCalledWith("boardUndoRunning");
    expect(view.latest().items[0].run?.status, "在跑的一格撤不没(任务照跑、钱照花)").toBe("running");
    expect(view.api().canUndo).toBe(true);

    act(() => view.landTiles("qr"));
    await settle();
    await undoKey();
    await settle();
    expect(ids(view.latest())).toEqual(["qr"]);
  });

  it("跑的时候又改了别的:撤那一下九格还在;再撤九格拿下;重做两下都回来 —— 画布上一时没有九格,照落下的那一版放回", async () => {
    const view = mount([image("qr", { asset_id: "a-qr" }), note("n1", "原来")]);
    await split("qr");
    act(() => view.api().patch("n1", { text: "跑的时候改的" }));
    await settle();
    act(() => view.landTiles("qr"));
    await settle();

    await undoKey();
    await settle();
    expect(view.latest().items.find((one) => one.id === "n1")?.text).toBe("原来");
    expect(ids(view.latest()), "撤的是那一下改字,九格还在").toHaveLength(11);
    expect(view.latest().items.find((one) => one.id === "qr")?.run?.status, "宿主照落下的终态,不回到「在跑」").toBe("succeeded");

    await undoKey();
    await settle();
    expect(ids(view.latest())).toEqual(["qr", "n1"]);

    await redoKey();
    await settle();
    expect(ids(view.latest())).toHaveLength(11);
    expect(view.latest().edges).toHaveLength(9);
    expect(view.latest().items.find((one) => one.id === "qr")?.run?.status).toBe("succeeded");
    expect(view.latest().items.find((one) => one.id === "n1")?.text).toBe("原来");

    await redoKey();
    await settle();
    expect(view.latest().items.find((one) => one.id === "n1")?.text).toBe("跑的时候改的");
    expect(ids(view.latest())).toHaveLength(11);
  });

  it("撤掉之后服务端那一版不把它们带回来:轮询拿到的还是有九格的一版,合进来照样没有;自动保存送出去的也没有", async () => {
    const view = mount([image("qr", { asset_id: "a-qr" }), note("n1", "")]);
    await split("qr");
    act(() => view.landTiles("qr"));
    await settle();
    await undoKey();
    await settle();
    expect(ids(view.latest())).toEqual(["qr", "n1"]);

    //: 保存还没落库时,轮询拿到了服务端更新的一版(别的一格改了),里面还是九格。
    const stale = view.server.confirmed;
    act(() => view.adoptServer({ ...stale, items: stale.items.map((one) => (one.id === "n1" ? { ...one, text: "智能体写的" } : one)) }));
    await settle();
    expect(ids(view.latest()), "撤掉的九格没被那一版带回来").toEqual(["qr", "n1"]);
    expect(view.latest().items.find((one) => one.id === "n1")?.text, "服务端那一版的别的改动照收").toBe("智能体写的");
    expect(view.changes.at(-1)?.edges).toEqual([]);
    expect(view.api().canRedo, "合进服务端那一版不冲掉重做").toBe(true);
  });
});

describe("就地填进空槽的一次运行", () => {
  it("撤下那张图:空槽回来、表单还在,说一声素材库里还在;重做放回", async () => {
    const view = mount([image("slot", { form: { producer: "node:x.paint" } })], { producers: [PAINT] });
    select("slot");
    await settle();
    await act(async () => {
      document.querySelector<HTMLButtonElement>("[data-board-composer-send]")!.click();
      await vi.advanceTimersByTimeAsync(10);
    });
    await settle();
    act(() => view.landFill("slot", "made"));
    await settle();
    expect(view.latest().items[0].asset_id).toBe("made");

    await undoKey();
    await settle();
    expect(view.latest().items[0].asset_id).toBeUndefined();
    expect(view.latest().items[0].form?.producer).toBe("node:x.paint");
    expect(toastMock.message).toHaveBeenCalledWith("boardUndoRunAssets");

    await redoKey();
    await settle();
    expect(view.latest().items[0]).toMatchObject({ asset_id: "made", run: { status: "succeeded" } });
  });

  it("一次出两张:一起摆好的占位落下第二张;撤一下两张都拿下,重做都回来", async () => {
    const view = mount([image("slot", { form: { producer: "node:x.paint" } })], { producers: [PAINT] });
    select("slot");
    await settle();
    await act(async () => {
      document.querySelector<HTMLButtonElement>("[data-board-composer-send]")!.click();
      await vi.advanceTimersByTimeAsync(10);
    });
    //: 服务端一次摆好的第二格占位(带着同一个任务号,见 outputs.sibling_placeholders)。
    const placed = view.server.confirmed;
    act(() => view.adoptServer({ ...placed, items: [...placed.items, image("slot-2", { x: 300, form: { producer: "node:x.paint" }, run: { status: "running", job_id: "job-1" } })] }));
    await settle();
    const waiting = view.server.confirmed;
    act(() => view.adoptServer({
      ...waiting,
      items: waiting.items.map((one) => ({ ...one, asset_id: one.id === "slot" ? "a1" : "a2", run: { status: "succeeded" as const } })),
    }));
    await settle();
    expect(view.latest().items.map((one) => one.asset_id)).toEqual(["a1", "a2"]);

    await undoKey();
    await settle();
    expect(ids(view.latest()), "第二张也是这一轮的,一起拿下").toEqual(["slot"]);
    expect(view.latest().items[0].asset_id).toBeUndefined();
    expect(toastMock.message).toHaveBeenCalledWith("boardUndoRunAssets");
    await redoKey();
    await settle();
    expect(view.latest().items.map((one) => one.asset_id)).toEqual(["a1", "a2"]);
  });

  it("没跑起来(被拒、没同意):撤销里不多出一步", async () => {
    const view = mount([image("qr", { asset_id: "a-qr" })], { refuse: true });
    await split("qr");
    expect(view.api().canUndo).toBe(false);
  });
});

describe("不是人做的变化不记成一步", () => {
  it("图片加载出来按宽高比校正高度:不进撤销;之后撤人做的那一下,高度也不缩回去", async () => {
    const view = mount([{ id: "img", kind: "image", x: 0, y: 0, width: 260, height: 180, asset_id: "a1" }, note("n1", "")]);
    const picture = document.querySelector<HTMLImageElement>('[data-id="img"] img')!;
    Object.defineProperty(picture, "naturalWidth", { value: 1000 });
    Object.defineProperty(picture, "naturalHeight", { value: 500 });
    act(() => void fireEvent.load(picture));
    await settle();
    expect(view.latest().items[0].height).toBe(130);
    expect(view.api().canUndo, "校正不是一步").toBe(false);

    act(() => view.api().patch("n1", { text: "写了一句" }));
    await settle();
    await undoKey();
    await settle();
    expect(view.latest().items[1].text).toBe("");
    expect(view.latest().items[0].height).toBe(130);
    expect(view.api().canUndo).toBe(false);
  });

  it("服务端纠正回来的运行态和产出(存回去之后、轮询收尾时):不进撤销", async () => {
    const view = mount([image("img", { run: { status: "running", job_id: "j" } })]);
    act(() => view.api().absorb("img", { asset_id: "a1", run: { status: "succeeded" } }));
    await settle();
    expect(view.latest().items[0].asset_id).toBe("a1");
    expect(view.api().canUndo).toBe(false);
  });

  it("面板一挂上就接好的默认绑定不是一步;撤 / 重做之后面板照装回去的重挂,重做不被它冲掉", async () => {
    const view = mount([image("img", { asset_id: "a1" }), note("n1", "一段配文")], {
      producers: [CAPTION],
      edges: [{ id: "e", source: "n1", target: "img" }],
    });
    select("img");
    act(() => document.querySelector<HTMLButtonElement>('[data-board-abilities] button[aria-label="配文"]')!.click());
    await settle();
    const chip = () => document.querySelector<HTMLButtonElement>('[data-binding-source="n1"]')!;
    expect(chip().getAttribute("aria-pressed"), "连进来的便签默认接上").toBe("true");
    expect(view.api().canUndo, "面板自己补的不是一步").toBe(false);

    //: 人点了一下:不接这张便签了。
    act(() => {
      fireEvent.pointerDown(chip());
      chip().click();
    });
    await settle();
    expect(chip().getAttribute("aria-pressed")).toBe("false");
    expect(view.api().canUndo).toBe(true);

    await undoKey();
    await settle();
    expect(chip().getAttribute("aria-pressed"), "面板照装回去的表单重挂:又接上了").toBe("true");
    expect(view.api().canRedo, "重挂的面板没把重做冲掉").toBe(true);
    await redoKey();
    await settle();
    expect(chip().getAttribute("aria-pressed")).toBe("false");
  });
});

describe("面板开着时撤 / 重做", () => {
  it("面板里的值跟着装回去的表单变 —— 不留着撤之前的字、下一次改动再把它写回去;重做不被重挂的面板冲掉", async () => {
    const view = mount([{ id: "au", kind: "audio", x: 0, y: 0, width: 280, height: 72, form: { producer: "speak", prompt: "原来的旁白" } }], { producers: [] });
    select("au");
    await settle();
    const box = () => document.querySelector<HTMLTextAreaElement>("[data-board-composer] textarea")!;
    expect(box().value).toBe("原来的旁白");
    expect(view.api().canUndo, "面板挂上时补齐的表单不是一步").toBe(false);
    act(() => {
      box().focus();
      fireEvent.keyDown(box(), { key: "a" });
      fireEvent.change(box(), { target: { value: "改过的旁白" } });
    });
    await settle();
    act(() => box().blur());
    await settle();
    expect(view.latest().items[0].form?.prompt).toBe("改过的旁白");

    await undoKey();
    await settle();
    expect(view.latest().items[0].form?.prompt).toBe("原来的旁白");
    expect(box().value, "面板照装回去的表单重挂").toBe("原来的旁白");
    expect(view.api().canRedo).toBe(true);
    await redoKey();
    await settle();
    expect(box().value).toBe("改过的旁白");
  });
});

describe("一步 = 人做的一下", () => {
  it("停手不到 400ms 就按撤销:撤的是刚做的那一下,不是它前面那一下(此前那一下丢了)", async () => {
    const view = mount([note("n1", "")]);
    act(() => view.api().patch("n1", { text: "一" }));
    await settle();
    act(() => view.api().patch("n1", { text: "二" }));
    await undoKey();
    await settle();
    expect(view.latest().items[0].text).toBe("一");
    await redoKey();
    await settle();
    expect(view.latest().items[0].text).toBe("二");
  });

  it("在便签里打字,中间停多久都是一步;离开那个框才记", async () => {
    const view = mount([note("n1", "原来")]);
    act(() => void fireEvent.doubleClick(document.querySelector('[data-id="n1"] > div')!));
    const box = document.querySelector<HTMLTextAreaElement>('[data-id="n1"] textarea')!;
    act(() => box.focus());
    for (const value of ["原来的", "原来的一", "原来的一句"]) {
      act(() => void fireEvent.change(box, { target: { value } }));
      await settle(900);
    }
    expect(view.latest().items[0].text, "照常汇给自动保存").toBe("原来的一句");
    expect(view.api().canUndo, "还在框里:不记").toBe(false);
    act(() => box.blur());
    await settle();
    expect(view.api().canUndo).toBe(true);
    await undoKey();
    await settle();
    expect(view.latest().items[0].text, "一下回到打字之前").toBe("原来");
  });
});

describe("打着字时服务端落下了一版", () => {
  it("这段字还是一步:撤一下回到打字之前,服务端落下的那一格照留", async () => {
    const view = mount([note("n1", "原来"), image("img", { x: 400, run: { status: "running", job_id: "j" } })]);
    act(() => void fireEvent.doubleClick(document.querySelector('[data-id="n1"] > div')!));
    const box = document.querySelector<HTMLTextAreaElement>('[data-id="n1"] textarea')!;
    act(() => box.focus());
    act(() => void fireEvent.change(box, { target: { value: "原来的" } }));
    await settle();
    //: 别处点的那一格这时落下了产出(轮询采用的那一版)。
    const base = view.server.confirmed;
    act(() => view.adoptServer({ ...base, items: base.items.map((one) => (one.id === "img" ? { ...one, asset_id: "made", run: { status: "succeeded" as const } } : one)) }));
    await settle();
    act(() => void fireEvent.change(box, { target: { value: "原来的一句" } }));
    await settle();
    act(() => box.blur());
    await settle();
    expect(view.latest().items[0].text).toBe("原来的一句");
    await undoKey();
    await settle();
    expect(view.latest().items[0].text, "一下回到打字之前,不停在落下那一刻打到一半的字").toBe("原来");
    expect(view.latest().items[1].asset_id, "落下的那一张照留").toBe("made");
    expect(view.api().canUndo).toBe(false);
  });
});

describe("每一种操作:一步,撤回原样,重做回来", () => {
  const clipboard = new Map<string, string>();
  const clip = (type: "copy" | "paste") => {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { files: [], getData: (kind: string) => clipboard.get(kind) ?? "", setData: (kind: string, value: string) => clipboard.set(kind, value) },
    });
    act(() => {
      document.body.focus();
      document.body.dispatchEvent(event);
    });
  };
  const pressOn = (id: string, letter: string) =>
    act(() => {
      node(id).focus();
      node(id).dispatchEvent(new KeyboardEvent("keydown", { key: letter, bubbles: true }));
    });
  const board = () => [note("n1", "一", { x: 0 }), image("img", { x: 300, asset_id: "a1" })];
  const linked = [{ id: "e1", source: "n1", target: "img" }];
  const generated = image("gen", { x: 600, asset_id: "made", run: { status: "succeeded" } });
  const cases: { name: string; items?: BoardItem[]; act: (view: ReturnType<typeof mount>) => void | Promise<void> }[] = [
    { name: "添加一格", act: (view) => void act(() => void view.api().add("note")) },
    { name: "删一格,连着它的线一起删", act: () => { select("n1"); pressOn("n1", "Backspace"); } },
    { name: "复制选中的(连带它们之间的线)", act: () => { select("n1"); act(() => document.querySelector<HTMLButtonElement>('.react-flow__node-toolbar button[aria-label="copy"]')!.click()); } },
    { name: "⌘C / ⌘V 粘贴格子", act: () => { clipboard.clear(); select("n1"); clip("copy"); clip("paste"); } },
    { name: "便签换颜色", act: () => { select("n1"); act(() => document.querySelector<HTMLButtonElement>('[aria-label="boardNoteColorBlue"]')!.click()); } },
    { name: "换一份素材(从素材选择器挑)", act: () => { select("img"); act(() => document.querySelector<HTMLButtonElement>('[data-board-abilities] button[aria-label="boardReplaceAsset"]')!.click()); } },
    { name: "生成出来的那张换一份素材:撤回去是生成的那张", items: [...board(), generated], act: () => { select("gen"); act(() => document.querySelector<HTMLButtonElement>('[data-board-abilities] button[aria-label="boardReplaceAsset"]')!.click()); } },
    { name: "放一枚位置标记", act: (view) => void act(() => view.api().addMarker()) },
  ];
  for (const one of cases) {
    it(one.name, async () => {
      const view = mount(one.items ?? board(), { edges: linked, producers: [], onPickAsset: (_kind, place) => place("picked") });
      await settle();
      const before = JSON.stringify(view.api().flush());
      await one.act(view);
      await settle();
      await settle();
      const after = JSON.stringify(view.api().flush());
      expect(after, "做了点什么").not.toBe(before);
      expect(view.api().canUndo).toBe(true);
      await undoKey();
      await settle();
      expect(JSON.stringify(view.api().flush()), "一下撤回原样").toBe(before);
      expect(view.api().canUndo, "只有这一步").toBe(false);
      await redoKey();
      await settle();
      expect(JSON.stringify(view.api().flush()), "重做回来").toBe(after);
    });
  }
});

describe("拖着、拉着大小的时候不记,松手才记一步", () => {
  it("拖到一半停下来也不拆成两步", () => {
    vi.useFakeTimers();
    const start = toNodes([note("n1", "")]);
    const { result } = renderHook(
      () => {
        const [nodes, setNodes] = React.useState<Node[]>(start);
        const [edges, setEdges] = React.useState<Edge[]>([]);
        const surface = React.useRef<HTMLElement | null>(null);
        return { setNodes, ...useBoardHistory({ nodes, edges, setNodes, setEdges, onChange: () => undefined, surface }) };
      },
      { wrapper: ({ children }) => <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider> },
    );
    const drag = (x: number, dragging: boolean) =>
      act(() => result.current.setNodes((nodes) => nodes.map((one) => ({ ...one, position: { x, y: 0 }, dragging }))));
    drag(10, true);
    act(() => void vi.advanceTimersByTime(800));
    drag(40, true);
    act(() => void vi.advanceTimersByTime(800));
    expect(result.current.history.past, "手还没松").toHaveLength(0);
    drag(60, false);
    act(() => void vi.advanceTimersByTime(400));
    expect(result.current.history.past).toHaveLength(1);
    act(() => result.current.stepBack());
    expect(JSON.parse(result.current.history.present).items[0].x, "一下回到拖之前").toBe(0);
  });
});
