/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const editor = vi.hoisted(() => ({ undoSequence: vi.fn(), redoSequence: vi.fn(), appendAssetToSequence: vi.fn(), getSequence: vi.fn() }));
vi.mock("@/api/domains/editor", async (original) => ({ ...(await original<object>()), ...editor }));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import type { BoardCanvas as Canvas } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";
import { rebaseCanvas } from "@/features/boards/boardRebase";
import { noteSequenceEdit } from "@/features/boards/sequenceCursor";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  vi.useRealTimers();
});

function mount(canvas: Canvas, extra: Partial<React.ComponentProps<typeof BoardCanvas>> = {}) {
  let api: BoardCanvasApi | null = null;
  const changes: Canvas[] = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
      <div style={{ width: 800, height: 600 }}>
        <BoardCanvas
          boardId="b1"
          workspaceId="w1"
          canvas={canvas}
          onChange={(next) => changes.push(next)}
          onPickAsset={() => undefined}
          onReady={(next) => {
            api = next;
          }}
          {...extra}
        />
      </div>
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  return { api: () => api as unknown as BoardCanvasApi, latest: () => changes[changes.length - 1] };
}

const note = (id: string, text: string) => ({ id, kind: "note" as const, x: 0, y: 0, width: 220, height: 140, color: "yellow" as const, text });

describe("画板的撤销与服务端那份", () => {
  it("采用服务端的新一版之后撤销历史还在:撤一步撤的是自己刚做的,服务端刚落下的格子和产出照留", async () => {
    const view = mount({ items: [note("n1", ""), { id: "img", kind: "image", x: 300, y: 0, width: 260, height: 180, run: { status: "running", job_id: "j" } }], edges: [], markers: [] });
    // 本地写了一句,攒够一步进历史;这一句已经存上(服务端那份里就有)。
    act(() => view.api().patch("n1", { text: "我写的" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    const saved = view.latest();

    // 服务端又推进了一版:那张图出来了,智能体加了一张便签。
    const server: Canvas = {
      items: [saved.items[0], { ...saved.items[1], asset_id: "a1", run: { status: "succeeded" } }, note("agent", "智能体加的")],
      edges: [],
      markers: [],
    };
    act(() => view.api().adopt(rebaseCanvas(saved, view.latest(), server).canvas, (snapshot) => rebaseCanvas(saved, snapshot, server).canvas));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(view.api().canUndo, "回执落地不清空撤销历史").toBe(true);

    act(() => view.api().undo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    const undone = view.latest();
    expect(undone.items.find((one) => one.id === "n1")?.text, "撤的是自己写的那句").toBe("");
    expect(undone.items.map((one) => one.id)).toContain("agent");
    expect(undone.items.find((one) => one.id === "img")?.asset_id, "撤销不撤回刚落下的产出").toBe("a1");
  });

  it("时间线格里剪的一刀也在画板的撤销里:按做的先后退,退到它时调那条时间线的撤销、画布不动;重做同理", async () => {
    editor.undoSequence.mockResolvedValue({ id: "seq", tracks: [], revision: 4 });
    editor.redoSequence.mockResolvedValue({ id: "seq", tracks: [], revision: 5 });
    const view = mount({ items: [note("n1", "")], edges: [], markers: [] });
    act(() => view.api().patch("n1", { text: "先写一句" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    //: 格子里剪了一刀(SequenceCell 做成之后发这条通知)。
    act(() => noteSequenceEdit("seq", 3));

    act(() => view.api().undo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(editor.undoSequence).toHaveBeenCalledTimes(1);
    expect(editor.undoSequence, "带着这一步做完时的版本号去撤").toHaveBeenCalledWith("seq", 3);
    expect(view.latest().items[0]?.text, "撤的是时间线那一刀,画布上的字还在").toBe("先写一句");

    act(() => view.api().undo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(editor.undoSequence).toHaveBeenCalledTimes(1);
    expect(view.latest().items[0]?.text).toBe("");

    act(() => view.api().redo());
    act(() => view.api().redo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(editor.redoSequence, "重做照撤销回来的那一版比").toHaveBeenCalledWith("seq", 4);
    expect(view.latest().items[0]?.text).toBe("先写一句");
  });

  it("时间线在别处改过:撤那一步被拒,这一步从摞里拿掉,下一次 ⌘Z 退的是画布", async () => {
    editor.undoSequence.mockReset();
    editor.redoSequence.mockReset();
    editor.undoSequence.mockRejectedValue(new Error("这条时间线在别处改过"));
    const view = mount({ items: [note("n1", "")], edges: [], markers: [] });
    act(() => view.api().patch("n1", { text: "先写一句" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    act(() => noteSequenceEdit("seq", 3));

    act(() => view.api().undo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(editor.undoSequence).toHaveBeenCalledWith("seq", 3);
    act(() => view.api().redo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(editor.redoSequence, "撤不成的那一步不留在重做里").not.toHaveBeenCalled();

    act(() => view.api().undo());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(editor.undoSequence).toHaveBeenCalledTimes(1);
    expect(view.latest().items[0]?.text, "下一步退的是画布上的字").toBe("");
  });
});

describe("给一格改名", () => {
  const image = (id: string, title?: string) => ({ id, kind: "image" as const, x: 0, y: 0, width: 260, height: 180, ...(title ? { title } : {}) });

  async function settle() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
  }

  it("操作条上的「重命名」打开名字那一处;打完一个名字是撤销历史里的一步", async () => {
    const view = mount({ items: [image("a"), image("b", "侧面")], edges: [], markers: [] });
    const node = document.querySelector('[data-id="a"]') as HTMLElement;
    act(() => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();
    expect(view.api().canUndo).toBe(false);

    const rename = document.querySelector<HTMLButtonElement>('.react-flow__node-toolbar button[aria-label="rename"]');
    expect(rename, "单选一格时操作条上有「重命名」").not.toBeNull();
    act(() => rename!.click());
    const input = node.querySelector<HTMLInputElement>('input[aria-label="rename"]')!;
    expect(input, "输入框开在这一格上方的名字那一处").not.toBeNull();

    //: 一个字一个字地打:每一下都只进草稿,不进画布 —— 否则攒不成一步。
    for (const value of ["正", "正面", "正面特写"]) {
      fireEvent.change(input, { target: { value } });
      await settle();
    }
    expect(view.latest().items.find((one) => one.id === "a")?.title).toBeUndefined();
    expect(view.api().canUndo).toBe(false);

    fireEvent.keyDown(input, { key: "Enter" });
    await settle();
    expect(view.latest().items.map((one) => one.title)).toEqual(["正面特写", "侧面"]);
    expect(node.querySelector("[data-board-node-label]")?.textContent).toBe("正面特写");

    act(() => view.api().undo());
    await settle();
    expect(view.latest().items.map((one) => one.title)).toEqual([undefined, "侧面"]);
    expect(view.api().canUndo).toBe(false);
  });
});

describe("删除键只认冲着画布来的那一下", () => {
  //: 和工作流编辑器同一条规矩(lib/shortcuts 的 isCanvasKeyTarget):焦点停在面板里的按钮上、
  //: 或者在 Portal 到 body 的下拉选项上时按 Backspace,是冲着那个控件去的,不是删选中的那一格。
  const board: Canvas = { items: [note("n1", "留着"), note("n2", "也留着")], edges: [], markers: [] };

  function select(id: string) {
    const node = document.querySelector(`[data-id="${id}"]`) as HTMLElement;
    act(() => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  }

  async function press(target: HTMLElement, key: string) {
    act(() => {
      target.focus();
      target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
  }

  const ids = (view: ReturnType<typeof mount>) => view.latest()?.items.map((one) => one.id) ?? ["n1", "n2"];

  it("焦点在面板的按钮上:不删", async () => {
    const view = mount(board);
    select("n1");
    const button = document.querySelector<HTMLElement>(".react-flow__node-toolbar button");
    expect(button, "选中之后应该有浮在节点上的面板").not.toBeNull();
    await press(button!, "Backspace");
    expect(ids(view)).toEqual(["n1", "n2"]);
  });

  it("焦点在 Portal 出去的下拉选项上:不删", async () => {
    const view = mount(board);
    select("n1");
    const option = document.createElement("div");
    option.setAttribute("role", "option");
    option.tabIndex = -1;
    document.body.appendChild(option);
    await press(option, "Delete");
    option.remove();
    expect(ids(view)).toEqual(["n1", "n2"]);
  });

  it("焦点在画布上:照常删", async () => {
    const view = mount(board);
    select("n1");
    await press(document.querySelector<HTMLElement>('[data-id="n1"]')!, "Backspace");
    expect(view.latest().items.map((one) => one.id)).toEqual(["n2"]);
  });
});

describe("跳到标记", () => {
  it("快捷键跳过去和清单里点一样,先把藏起来的标记显示出来", async () => {
    const onRevealMarkers = vi.fn();
    mount(
      { items: [], edges: [], markers: [{ id: "m1", name: "开头", x: 10, y: 20, shortcut: "Alt+1" }] },
      { markersVisible: false, onRevealMarkers },
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    act(() => {
      fireEvent.keyDown(window, { key: "1", code: "Digit1", altKey: true });
    });
    expect(onRevealMarkers).toHaveBeenCalledTimes(1);
  });
});

describe("往画布上粘贴", () => {
  //: 粘贴冲着画布来才接(和删除键同一条判据,isCanvasKeyTarget):在输入框、编辑器里粘贴是往那儿贴字。
  function paste(target: HTMLElement, data: { text?: string; files?: File[] }) {
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { files: data.files ?? [], getData: (type: string) => (type === "text/plain" ? (data.text ?? "") : "") },
    });
    act(() => {
      target.focus();
      target.dispatchEvent(event);
    });
    return event;
  }

  async function settle() {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
  }

  it("一段文字落成一张便签", async () => {
    const view = mount({ items: [note("n1", "原来的")], edges: [], markers: [] });
    const event = paste(document.body, { text: "粘进来的想法" });
    await settle();
    expect(event.defaultPrevented).toBe(true);
    const added = view.latest().items.find((one) => one.id !== "n1");
    expect(added).toMatchObject({ kind: "note", text: "粘进来的想法", form: { producer: "write" } });
  });

  it("截图先进素材库,再按种类放一格", async () => {
    const onDropFiles = vi.fn(async (files: File[]) =>
      files.map((file, index) => ({ id: `a${index}`, name: file.name, kind: "image" as const })),
    );
    const view = mount({ items: [note("n1", "原来的")], edges: [], markers: [] }, { onDropFiles });
    paste(document.body, { files: [new File([new Uint8Array([1])], "", { type: "image/png" })], text: "<img>" });
    await settle();
    expect(onDropFiles).toHaveBeenCalledTimes(1);
    const added = view.latest().items.find((one) => one.id !== "n1");
    expect(added).toMatchObject({ kind: "image", asset_id: "a0" });
  });

  it("评论 / 标记模式下拖文件进来和粘贴一样不接:画布这时只收批注", async () => {
    const png = () => new File([new Uint8Array([1])], "shot.png", { type: "image/png" });
    const dropOn = () => {
      const file = png();
      act(() => {
        fireEvent.drop(document.querySelector(".react-flow")!, { dataTransfer: { types: ["Files"], files: [file], items: [] } });
      });
    };
    const placed = async (files: File[]) => files.map((file, index) => ({ id: `a${index}`, name: file.name, kind: "image" as const }));

    //: 对照:平常拖进来是接的 —— 否则下面两句是在一个根本收不到拖放的桩上断言。
    const onDropFiles = vi.fn(placed);
    mount({ items: [note("n1", "原来的")], edges: [], markers: [] }, { onDropFiles });
    dropOn();
    await settle();
    expect(onDropFiles).toHaveBeenCalledTimes(1);
    cleanup();

    for (const mode of [{ commentMode: true }, { markerMode: true }]) {
      const blocked = vi.fn(placed);
      mount({ items: [note("n1", "原来的")], edges: [], markers: [] }, { onDropFiles: blocked, ...mode });
      dropOn();
      paste(document.body, { files: [png()] });
      await settle();
      expect(blocked, JSON.stringify(mode)).not.toHaveBeenCalled();
      cleanup();
    }
  });

  it("焦点在输入框里:不接,交给那个输入框", async () => {
    const view = mount({ items: [note("n1", "原来的")], edges: [], markers: [] });
    const input = document.createElement("textarea");
    document.querySelector(".react-flow")!.appendChild(input);
    const event = paste(input, { text: "打进输入框的字" });
    await settle();
    input.remove();
    expect(event.defaultPrevented).toBe(false);
    expect(view.latest()?.items.map((one) => one.id) ?? ["n1"]).toEqual(["n1"]);
  });
});

describe("截挂了的那一格,选中时挂的是截取面板", () => {
  it("范围原样在,重截落回这一格;不挂生成面板", async () => {
    const onRun = vi.fn(async () => undefined);
    const cut = {
      id: "cut",
      kind: "video" as const,
      x: 0,
      y: 0,
      width: 320,
      height: 200,
      form: { trim: { asset_id: "src", start: 1.5, end: 4, mute: true }, producer: "trim" as const },
      run: { status: "failed" as const, error: "截取失败" },
    };
    mount({ items: [cut], edges: [], markers: [] }, { onRun, models: [] });

    const node = document.querySelector('[data-id="cut"]') as HTMLElement;
    act(() => {
      node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });

    const start = document.querySelector('[aria-label="boardTrimStartLabel"]') as HTMLInputElement | null;
    expect(start?.value).toBe("1.5");
    expect(document.querySelector('[aria-label="boardTrimEndLabel"]')).toHaveProperty("value", "4");
    expect(document.querySelector('[title="boardDropSound"]')).not.toBeNull();

    //: 发送键是面板壳上那枚圆键(只有图标,名字在 aria-label 上)。
    const submit = document.querySelector<HTMLButtonElement>('[data-board-composer="trim"] button[aria-label="boardTrimSubmit"]');
    act(() => submit!.click());
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun).toHaveBeenCalledWith(expect.objectContaining({
      producer: "trim",
      item_id: "cut",
      form: { asset_id: "src", start: 1.5, end: 4, mute: true },
    }));
  });
});

describe("选中之后挂什么", () => {
  const select = (id: string) =>
    act(() => {
      document.querySelector(`[data-id="${id}"]`)!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  //: 操作条上的动作是一排图标:名字在 aria-label 上(读屏和悬停读它)。
  const toolbarButton = (label: string) =>
    [...document.querySelectorAll<HTMLButtonElement>(".react-flow__node-toolbar button")].find(
      (one) => one.getAttribute("aria-label") === label || one.textContent?.includes(label),
    );
  const writeNote = (id: string, extra: Record<string, unknown> = {}) =>
    ({ ...note(id, "开场白"), form: { producer: "write" as const }, ...extra });

  it("选中一张便签不弹写作面板 —— 挪一挪它不用先关掉什么;操作条上「让 AI 写」才打开,再点一次收起", () => {
    mount({ items: [writeNote("n1")], edges: [], markers: [] }, { onRun: vi.fn(async () => undefined) });
    select("n1");
    expect(document.querySelector('[data-board-composer="write"]')).toBeNull();
    const ask = toolbarButton("boardAskAiWrite");
    expect(ask, "操作条上有「让 AI 写」").toBeTruthy();
    act(() => ask!.click());
    expect(document.querySelector('[data-board-composer="write"]')).not.toBeNull();
    expect(toolbarButton("boardAskAiWrite")!.getAttribute("aria-pressed")).toBe("true");
    act(() => toolbarButton("boardAskAiWrite")!.click());
    expect(document.querySelector('[data-board-composer="write"]')).toBeNull();
  });

  it("空文档格点一下只是选中;引用笔记在上方操作条,和「让 AI 写」挨着", () => {
    mount({ items: [{ id: "d1", kind: "document", x: 0, y: 0, form: { producer: "write" } }], edges: [], markers: [] },
      { onRun: vi.fn(async () => undefined) });
    const empty = document.querySelector('[data-id="d1"] [data-document-empty]');
    expect(empty, "空状态画出来了").not.toBeNull();
    expect(empty!.closest("button"), "空状态不是一个按钮 —— 点它不弹挑笔记").toBeNull();
    select("d1");
    expect(toolbarButton("documentPick"), "操作条上有「引用笔记」").toBeTruthy();
    expect(toolbarButton("boardAskAiWrite"), "文档格也能让 AI 写一篇").toBeTruthy();
    act(() => toolbarButton("documentPick")!.click());
    expect(document.querySelector('[role="dialog"]'), "点了才弹挑笔记").not.toBeNull();
  });

  //: 和文档格的「转为笔记」同一种挂法:操作条上的一个动作。此前它挂在便签格子外面,多选几张便签各冒一颗。
  it("便签的「保存到笔记」在操作条上,点了才弹;多选时操作条只给共通动作,没有它", () => {
    mount({ items: [note("n1", "一段想法"), note("n2", "另一段")], edges: [], markers: [] });
    const action = () => document.querySelector<HTMLButtonElement>('.react-flow__node-toolbar [data-board-action="note-to-note"]');
    select("n1");
    expect(action(), "操作条上有「保存到笔记」").not.toBeNull();
    const onCell = [...document.querySelectorAll('[data-id="n1"] button')].filter((one) => one.textContent?.includes("保存到笔记"));
    expect(onCell, "格子自己身上不再挂这颗按钮").toEqual([]);

    //: 按住多选键、点第二张:三步分开 act —— 多选键按下要先落进 React Flow 的状态,点击才认它。
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Control", ctrlKey: true }));
    });
    act(() => {
      document.querySelector('[data-id="n2"]')!.dispatchEvent(new MouseEvent("click", { bubbles: true, ctrlKey: true }));
    });
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keyup", { key: "Control" }));
    });
    expect(document.querySelectorAll(".react-flow__node.selected")).toHaveLength(2);
    expect(action(), "多选时没有它").toBeNull();

    select("n1");
    act(() => action()!.click());
    expect(document.querySelector('[role="dialog"]'), "点了才弹").not.toBeNull();
  });

  it("没有字的便签不给「保存到笔记」—— 存不出东西", () => {
    mount({ items: [note("n1", "  ")], edges: [], markers: [] });
    select("n1");
    expect(document.querySelector('[data-board-action="note-to-note"]')).toBeNull();
  });

  it("工具交回的 JSON 便签没有「让 AI 写」", () => {
    mount({ items: [writeNote("j1", { text: '{"a":1}', text_format: "json" })], edges: [], markers: [] }, { onRun: vi.fn(async () => undefined) });
    select("j1");
    expect(toolbarButton("boardAskAiWrite")).toBeUndefined();
    expect(document.querySelector('[data-board-composer="write"]')).toBeNull();
  });

  it("3D 场景格的「编辑场景」在操作条上,不跟着面板走 —— 切到「按文字搭」也还在(用户截图:切过去就找不到了)", () => {
    for (const producer of ["scene_render", "node:scene_from_text"] as const) {
      mount(
        { items: [{ id: "sc", kind: "scene", x: 0, y: 0, width: 320, height: 220, scene_id: "scene-1", text: "草原", form: { producer } }],
          edges: [], markers: [] },
        { onRun: vi.fn(async () => undefined) },
      );
      select("sc");
      const open = document.querySelector<HTMLAnchorElement>("[data-board-scene-open]");
      expect(open?.getAttribute("href"), producer).toBe("#/scenes?scene=scene-1");
      cleanup();
    }
    mount({ items: [{ id: "empty", kind: "scene", x: 0, y: 0, width: 320, height: 220, form: { producer: "node:scene_from_text" } }],
            edges: [], markers: [] }, { onRun: vi.fn(async () => undefined) });
    select("empty");
    expect(document.querySelector("[data-board-scene-open]"), "还没有场景就没有可编辑的").toBeNull();
  });

  describe("时间线格(ADR 0030)", () => {
    const clip = (id: string, start: number) => ({ id, asset_id: `a-${id}`, asset_kind: "video", timeline_start: start, src_in: 0, src_out: 2, speed: 1 });
    const SEQUENCE = { id: "seq", project_id: "p", width: 1080, height: 1920,
                       tracks: [{ id: "v", kind: "video", position: 0, clips: [clip("a", 0), clip("b", 2)] }] };
    const EXPORT = {
      id: "sequence_export", type: "sequence_export", runs_from_draft: true, hosts: ["sequence"], role: "slot",
      fills_empty_slot: true, label: "导出成片", description: "", outputs: ["asset_id"],
      config: {
        resolution: { type: "string", default: "original", options: ["original", "720p"], option_labels: { original: "原样", "720p": "720p" }, label: "resolution" },
        quality: { type: "string", default: "standard", options: ["standard", "compact"], label: "quality" },
        ai_label: { type: "string", default: "yes", options: ["yes", "no"], label: "ai_label" },
      },
    };
    const board = {
      items: [
        { id: "t", kind: "sequence" as const, x: 0, y: 0, width: 560, height: 400, sequence_id: "seq", text: "时间线 1",
          form: { producer: "sequence_export" as const } },
        { id: "v1", kind: "video" as const, x: 700, y: 0, asset_id: "clip-1" },
        { id: "v2", kind: "video" as const, x: 700, y: 300, asset_id: "clip-1" },
      ],
      edges: [], markers: [],
    };

    it("选中时间线格不弹导出面板;操作条上「导出」才打开,发送起一次导出(只发导出自己的几项)", async () => {
      editor.getSequence.mockResolvedValue(SEQUENCE);
      const onRun = vi.fn(async () => undefined);
      mount(board, { onRun, producers: [EXPORT] as never });
      select("t");
      expect(document.querySelector('[data-board-composer="sequence-export"]'), "选中多半是要剪、要排").toBeNull();
      const exportButton = toolbarButton("boardSequenceExport");
      expect(exportButton, "操作条上有「导出」").toBeTruthy();
      act(() => exportButton!.click());
      const panel = document.querySelector('[data-board-composer="sequence-export"]');
      expect(panel).not.toBeNull();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10);
      });
      //: 时间线有两段:说的是几段、多长、画幅,不是「还是空的」。
      expect(panel!.querySelector("[data-sequence-export-summary]")?.textContent).toContain("boardSequenceExportSummary");
      act(() => panel!.querySelector<HTMLButtonElement>('button[aria-label="boardSequenceExport"]')!.click());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10);
      });
      expect(onRun).toHaveBeenCalledWith(expect.objectContaining({ producer: "sequence_export", item_id: "t", kind: "sequence", form: { config: {} } }));
    });

    it("条末尾的「+」开素材选择器(先列这张画板上的素材),挑中就接到末尾、记进撤销", async () => {
      editor.getSequence.mockResolvedValue(SEQUENCE);
      editor.appendAssetToSequence.mockResolvedValue(SEQUENCE);
      const onPickAsset = vi.fn();
      mount(board, { onPickAsset });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10);
      });
      const add = document.querySelector<HTMLButtonElement>("[data-sequence-add]");
      expect(add, "条末尾有「+」").not.toBeNull();
      act(() => add!.click());
      expect(onPickAsset).toHaveBeenCalledWith("media", expect.any(Function), { onBoard: ["clip-1"] });
      await act(async () => {
        onPickAsset.mock.calls[0][1]("clip-1");
        await vi.advanceTimersByTimeAsync(10);
      });
      expect(editor.appendAssetToSequence).toHaveBeenCalledWith("seq", "clip-1");
    });
  });

  it("空的图片槽选中就挂生成面板(那一格就是要生成的)", () => {
    mount(
      { items: [{ id: "i1", kind: "image", x: 0, y: 0, width: 260, height: 180, form: { producer: "generate" } }], edges: [], markers: [] },
      { onRun: vi.fn(async () => undefined) },
    );
    select("i1");
    expect(document.querySelector('[data-board-composer="generate"]')).not.toBeNull();
  });
});

describe("操作条上的「接着做」", () => {
  const select = (id: string) =>
    act(() => {
      document.querySelector(`[data-id="${id}"]`)!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  //: 「生成」是一颗按钮开一个菜单:一排「图片 视频 文案 音频」挤在操作条上,视频格上会把操作条撑出画布。
  const grow = () => {
    const trigger = document.querySelector<HTMLButtonElement>("[data-board-grow-menu]");
    if (!trigger) return [];
    act(() => trigger.click());
    const menu = screen.getByRole("menu", { name: "boardGrowLabel" });
    const rows = [...menu.querySelectorAll<HTMLElement>('[role="menuitem"]')];
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    return rows;
  };

  it("每一行把这一下说全,图标是要长出来的那种格子;便签不往下长文案", () => {
    mount({ items: [note("n1", "一只猫")], edges: [], markers: [] }, { onRun: vi.fn(async () => undefined) });
    select("n1");
    const rows = grow();
    //: 便签自己就是文案 —— 改写、翻译是它的能力,不再另长一张便签。
    expect(rows.map((row) => row.textContent)).toEqual([
      "boardSpawnImageFromNote", "boardSpawnVideoFromText", "boardSpawnAudio",
    ]);
    expect(rows[1].querySelector("svg.lucide-film")).not.toBeNull();
    expect(rows[2].querySelector("svg.lucide-music")).not.toBeNull();
  });

  it("有产出的图片往下接视频:拿它当首帧;空槽什么都不长", () => {
    mount(
      {
        items: [
          { id: "i1", kind: "image", x: 0, y: 0, width: 260, height: 180, asset_id: "a1" },
          { id: "i2", kind: "image", x: 400, y: 0, width: 260, height: 180, form: { producer: "generate" } },
        ],
        edges: [],
        markers: [],
      },
      { onRun: vi.fn(async () => undefined) },
    );
    select("i1");
    expect(grow().map((row) => row.textContent)).toEqual(["boardSpawnVideoFromImage", "boardSpawnNote"]);
    select("i2");
    expect(grow()).toEqual([]);
  });

  it("3D 场景往下接图片和视频,说的是场景的构图和镜头,不是「这张图当首帧」(用户截图);不长文案", () => {
    mount(
      { items: [{ id: "sc", kind: "scene", x: 0, y: 0, width: 320, height: 220, scene_id: "scene-1" }], edges: [], markers: [] },
      { onRun: vi.fn(async () => undefined) },
    );
    select("sc");
    expect(grow().map((row) => row.textContent)).toEqual(["boardSpawnImageFromScene", "boardSpawnVideoFromScene"]);
  });
});

describe("停止属于运行态的外壳", () => {
  it("在跑的生成格(不只工具格)上有停止,点了交给上层", () => {
    const onStop = vi.fn();
    mount(
      {
        items: [{ id: "i1", kind: "image", x: 0, y: 0, width: 260, height: 180, form: { producer: "generate", prompt: "猫" }, run: { status: "running", job_id: "job-1" } }],
        edges: [],
        markers: [],
      },
      { onStop },
    );
    const stop = document.querySelector<HTMLElement>('[data-id="i1"] [data-board-stop]');
    expect(stop).not.toBeNull();
    act(() => stop!.click());
    expect(onStop).toHaveBeenCalledWith("i1");
  });
});
