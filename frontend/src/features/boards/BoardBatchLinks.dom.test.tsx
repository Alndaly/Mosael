/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Connection, FinalConnectionState, ReactFlowInstance, ReactFlowProps } from "@xyflow/react";

/**
 * 多选之后一次连线走**选区框的统一出口**:选中两格以上,框右侧中点的 `+` 拉到一格上,选中的几格都连过去;拉到空白处,
 * 弹「新建一格,连上选中的 N 格」。格子自己的出口永远只连它自己。
 *
 * 统一出口是画布自己画的一层(BoardSelectionOutlet),在 jsdom 里能真的按下、拖动、松手:指针事件照流坐标换成屏幕坐标发。
 * 格子自己的出口是 React Flow 的接点,jsdom 里走不通一次真的拖线(接点要 ResizeObserver 量出位置),所以和
 * BoardPendingLink 的测试一样:在 React Flow 外面包一层记下画布交给它的 props,直接调 onConnect / onConnectEnd。
 */
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast: toastMocks }));
const editor = vi.hoisted(() => ({ undoSequence: vi.fn(), redoSequence: vi.fn(), appendAssetToSequence: vi.fn(), getSequence: vi.fn() }));
vi.mock("@/api/domains/editor", async (original) => ({ ...(await original<object>()), ...editor }));

const flow: { props: ReactFlowProps | null; instance: ReactFlowInstance | null } = { props: null, instance: null };
vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  function RecordingFlow(props: ReactFlowProps) {
    flow.props = props;
    return (
      <actual.ReactFlow
        {...props}
        onInit={(instance) => {
          flow.instance = instance as unknown as ReactFlowInstance;
          props.onInit?.(instance);
        }}
      />
    );
  }
  return { ...actual, ReactFlow: RecordingFlow };
});

import type { BoardCanvas as Canvas, BoardItem } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  flow.props = null;
  toastMocks.error.mockReset();
  Object.values(editor).forEach((one) => one.mockReset());
});
afterEach(() => {
  vi.useRealTimers();
});

async function settle(ms = 500) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function mount(canvas: Canvas) {
  let api: BoardCanvasApi | null = null;
  const changes: Canvas[] = [];
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ImagePreviewProvider>
        <div style={{ width: 800, height: 600 }}>
          <BoardCanvas boardId="b1" workspaceId="w1" canvas={canvas} onChange={(next) => changes.push(next)}
                       onPickAsset={() => undefined} onRun={async () => undefined} onReady={(next) => (api = next)} />
        </div>
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  await settle(10);
  await steadyViewport();
  return { api: () => api as unknown as BoardCanvasApi, latest: () => changes.at(-1) ?? canvas };
}

/**
 * 把视口摆成平移 0、缩放 1,**摆上了才往下走**。统一出口的拖动按视口在流坐标和屏幕坐标之间换算:整套并发跑、机器慢时,
 * 头一条用例里平移缩放器还没装好(对着还没量出尺寸的画布算出 NaN),换算出来的点就不是数(见 BoardPendingLink 的 zoomOut)。
 */
async function steadyViewport() {
  const target = { x: 0, y: 0, zoom: 1 };
  for (let attempt = 0; attempt < 50; attempt += 1) {
    await act(async () => {
      await flow.instance?.setViewport(target);
    });
    const now = flow.instance?.getViewport();
    if (now && now.x === target.x && now.y === target.y && now.zoom === target.zoom) return;
    await settle(10);
  }
  expect(flow.instance?.getViewport(), "视口一直没摆上 —— 画布的平移缩放器没装好").toEqual(target);
}

/** 选中这几格(React Flow 框选之后交给画布的就是这一串 select 变化)。 */
function pick(...ids: string[]) {
  act(() => {
    flow.props!.onNodesChange!(ids.map((id) => ({ id, type: "select", selected: true })));
  });
}
function connect(source: string, target: string) {
  act(() => {
    flow.props!.onConnect!({ source, target, sourceHandle: null, targetHandle: null } as Connection);
  });
}
const links = (canvas: Canvas) => canvas.edges.map((edge) => `${edge.source}->${edge.target}`).sort();

const image = (id: string, x: number, extra: Partial<BoardItem> = {}): BoardItem =>
  ({ id, kind: "image", x, y: 0, width: 260, height: 180, asset_id: `a-${id}`, ...extra });
const slot: BoardItem = { id: "slot", kind: "video", x: 0, y: 400, width: 320, height: 200, form: { producer: "generate" } };

type XY = { x: number; y: number };
const outlet = () => document.querySelector<HTMLButtonElement>("[data-selection-outlet]");
const selectionFrame = () => document.querySelector<HTMLElement>("[data-selection-frame]");
const draftLines = () =>
  [...document.querySelectorAll<SVGPathElement>("[data-selection-draft-line]")].map(
    (one) => `${one.getAttribute("data-selection-draft-line")}:${one.getAttribute("data-tone")}`,
  );
const nodeClass = (id: string) => document.querySelector<HTMLElement>(`.react-flow__node[data-id="${id}"]`)?.className ?? "";

/** 一个流坐标点在屏幕上的位置(jsdom 里画布的容器量出来是 0,换算只剩视口那一层)。 */
const screen = (point: XY) => flow.instance!.flowToScreenPosition(point);
/** 按住选区框的出口,拖到 `path` 上的每一点(流坐标)。松不松手由调用方定。 */
function dragOutlet(...path: XY[]) {
  const start = outlet()!.getBoundingClientRect();
  act(() => {
    outlet()!.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0, clientX: start.x, clientY: start.y }));
  });
  for (const point of path) {
    const at = screen(point);
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: at.x, clientY: at.y }));
    });
  }
}
function letGo(point: XY) {
  const at = screen(point);
  act(() => {
    window.dispatchEvent(new MouseEvent("pointerup", { clientX: at.x, clientY: at.y }));
  });
}
const middle = (item: BoardItem): XY => ({ x: item.x + (item.width ?? 0) / 2, y: item.y + (item.height ?? 0) / 2 });

describe("选区框的统一出口", () => {
  it("选中两格以上才有选区框和出口(出口上写着连几格);只选一格没有 —— 它用自己的出口", async () => {
    await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600), slot], edges: [], markers: [] });
    pick("i1");
    expect(selectionFrame()).toBeNull();
    expect(outlet()).toBeNull();
    pick("i2", "i3");
    expect(selectionFrame()).not.toBeNull();
    expect(outlet()?.textContent).toBe("3");
  });

  it("选中的里面只有分组框连不出线:框照画,出口只算连得出的格子;全是分组框就没有出口", async () => {
    const frame = (id: string, x: number): BoardItem => ({ id, kind: "frame", x, y: -60, width: 280, height: 300 });
    await mount({ items: [frame("f1", -20), frame("f2", 400), image("i1", 0)], edges: [], markers: [] });
    pick("f1", "f2");
    expect(selectionFrame()).not.toBeNull();
    expect(outlet(), "两个分组框:一格都连不出").toBeNull();
    pick("i1");
    expect(outlet()?.textContent).toBe("1");
  });

  it("从出口拖到生成格:一格一根预览线,悬在格子上把它圈出来;松手三张都连过去,撤一下三根一起没了", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600), slot], edges: [], markers: [] });
    pick("i1", "i2", "i3");
    dragOutlet({ x: 900, y: 900 });
    expect(draftLines(), "还在空白处:三根拖线途中的样子").toEqual(["i1:draft", "i2:draft", "i3:draft"]);
    dragOutlet(middle(slot));
    expect(draftLines()).toEqual(["i1:link", "i2:link", "i3:link"]);
    expect(nodeClass("slot")).toContain("outline-primary");
    letGo(middle(slot));
    await settle();
    expect(links(view.latest())).toEqual(["i1->slot", "i2->slot", "i3->slot"]);
    expect(draftLines(), "松手之后预览线收掉").toEqual([]);
    expect(nodeClass("slot"), "圈也收掉").not.toContain("outline-primary");
    expect(toastMocks.error).not.toHaveBeenCalled();

    act(() => view.api().undo());
    await settle();
    expect(view.latest().edges).toEqual([]);
  });

  it("拖到空白处松手:弹「新建一格,连上选中的 N 格」,新的一格把几格都连上;撤一下格子和线一起没了", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600)], edges: [], markers: [] });
    pick("i1", "i2", "i3");
    dragOutlet({ x: 1200, y: 600 });
    letGo({ x: 1200, y: 600 });
    expect(menu()?.textContent).toContain("boardSpawnTitleMany");
    const pendingSources = (flow.props!.edges ?? []).filter((edge) => (edge.data as { pending?: boolean } | undefined)?.pending).map((edge) => edge.source);
    expect(pendingSources, "每一格各一根待定的线接到占位上").toEqual(["i1", "i2", "i3"]);
    choose("boardKindVideo");
    await settle();
    const made = view.latest().items.find((one) => one.kind === "video")!;
    expect(made, "新的一格落在松手的地方(左边中点钉在松手点上)").toMatchObject({ x: 1200 });
    expect(links(view.latest())).toEqual([`i1->${made.id}`, `i2->${made.id}`, `i3->${made.id}`]);

    act(() => view.api().undo());
    await settle();
    expect(view.latest().items.map((one) => one.id)).toEqual(["i1", "i2", "i3"]);
    expect(view.latest().edges).toEqual([]);
  });

  it("Esc 取消:预览线和圈都没了,之后松手也不连、不弹单子", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), slot], edges: [], markers: [] });
    pick("i1", "i2");
    dragOutlet(middle(slot));
    expect(draftLines()).toHaveLength(2);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(draftLines()).toEqual([]);
    expect(nodeClass("slot")).not.toContain("outline-primary");
    letGo(middle(slot));
    await settle();
    expect(view.latest().edges).toEqual([]);
    expect(menu()).toBeNull();
  });

  it("连进时间线格:从左到右一段一段接(不照节点数组的先后);便签那根标成连不上、跳过并提示;撤一下线和片段一起回去", async () => {
    editor.appendAssetToSequence.mockResolvedValueOnce({ id: "seq", tracks: [], revision: 7 }).mockResolvedValueOnce({ id: "seq", tracks: [], revision: 8 });
    editor.undoSequence.mockResolvedValueOnce({ id: "seq", tracks: [], revision: 9 }).mockResolvedValueOnce({ id: "seq", tracks: [], revision: 10 });
    const note: BoardItem = { id: "n1", kind: "note", x: 0, y: 300, width: 220, height: 140, text: "旁白" };
    const timeline: BoardItem = { id: "t", kind: "sequence", x: 900, y: 0, width: 560, height: 400, sequence_id: "seq", form: { producer: "sequence_export" } };
    //: 数组里右边那张在前:按数组接的话会先接 a-right。
    const view = await mount({ items: [image("right", 600), image("left", 0), note, timeline], edges: [], markers: [] });
    pick("right", "left", "n1");
    dragOutlet(middle(timeline));
    expect(draftLines()).toEqual(["left:link", "n1:refused", "right:link"]);
    letGo(middle(timeline));
    await settle();
    await settle();
    expect(links(view.latest())).toEqual(["left->t", "right->t"]);
    expect(toastMocks.error).toHaveBeenCalledWith("boardLinksRefused");
    expect(editor.appendAssetToSequence.mock.calls, "从左到右,一段一段接").toEqual([["seq", "a-left"], ["seq", "a-right"]]);

    act(() => view.api().undo());
    await settle();
    expect(view.latest().edges, "两根新线一起撤掉").toEqual([]);
    expect(editor.undoSequence.mock.calls, "时间线上接的两段也一起撤,一次接一次").toEqual([["seq", { expectedRevision: 8 }], ["seq", { expectedRevision: 9 }]]);
  });

  it("已经连着的不算没连上:不提示", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), slot], edges: [{ id: "old", source: "i1", target: "slot" }], markers: [] });
    pick("i1", "i2");
    dragOutlet(middle(slot));
    letGo(middle(slot));
    await settle();
    expect(links(view.latest())).toEqual(["i1->slot", "i2->slot"]);
    expect(toastMocks.error).not.toHaveBeenCalled();
  });
});

/** 这一格自己的出入口 `+`(React Flow 的接点)此刻的显隐类。 */
const ports = (id: string) => [...document.querySelectorAll<HTMLElement>(`.react-flow__node[data-id="${id}"] .react-flow__handle`)];
function unpick(...ids: string[]) {
  act(() => {
    flow.props!.onNodesChange!(ids.map((id) => ({ id, type: "select", selected: false })));
  });
}

describe("多选之后的一下是撤销里的一步", () => {
  const roundTrip = async (view: Awaited<ReturnType<typeof mount>>, before: string) => {
    const after = JSON.stringify(view.api().flush());
    expect(after).not.toBe(before);
    act(() => view.api().undo());
    await settle();
    expect(JSON.stringify(view.api().flush()), "一下撤回原样").toBe(before);
    expect(view.api().canUndo).toBe(false);
    act(() => view.api().redo());
    await settle();
    expect(JSON.stringify(view.api().flush()), "重做回来").toBe(after);
  };

  it("⌘G 把选中的几格圈成一组", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300)], edges: [], markers: [] });
    const before = JSON.stringify(view.api().flush());
    pick("i1", "i2");
    act(() => void fireEvent.keyDown(document.body, { key: "g", metaKey: true }));
    await settle();
    expect(view.latest().items.map((one) => one.kind)).toEqual(["frame", "image", "image"]);
    await roundTrip(view, before);
  });

  it("连一根线", async () => {
    const view = await mount({ items: [image("i1", 0), slot], edges: [], markers: [] });
    const before = JSON.stringify(view.api().flush());
    connect("i1", "slot");
    await settle();
    expect(links(view.latest())).toEqual(["i1->slot"]);
    await roundTrip(view, before);
  });
});

describe("多选时格子自己的 `+` 只在悬停时露出", () => {
  it("只选一格:它的出入口一直露着(和原来一样)", async () => {
    await mount({ items: [image("i1", 0), image("i2", 300)], edges: [], markers: [] });
    pick("i1");
    expect(ports("i1")).toHaveLength(2);
    for (const port of ports("i1")) {
      expect(port.classList.contains("opacity-100"), "选中的那一格:+ 露着").toBe(true);
      expect(port.classList.contains("opacity-0")).toBe(false);
    }
  });

  it("选中两格以上:选中格子的 + 默认收起,悬停那一格时露出;退回只选一格又一直露着", async () => {
    await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600)], edges: [], markers: [] });
    pick("i1", "i2");
    for (const id of ["i1", "i2"]) {
      expect(ports(id)).toHaveLength(2);
      for (const port of ports(id)) {
        expect(port.classList.contains("opacity-0"), `${id}:默认收起`).toBe(true);
        expect(port.classList.contains("opacity-100")).toBe(false);
        //: 悬停露出靠的是格子外壳上的 group —— 和没选中的格子同一个机制。
        expect(port.classList.contains("group-hover:opacity-100"), `${id}:悬停那一格时露出`).toBe(true);
        expect(port.closest(".group"), `${id}:接点在格子的 group 里`).not.toBeNull();
      }
    }
    unpick("i2");
    for (const port of ports("i1")) expect(port.classList.contains("opacity-100"), "退回单选").toBe(true);
  });
});

describe("格子自己的出口只连它自己", () => {
  it("哪怕它在一组选中的格子里:拉到生成格只连这一格", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600), slot], edges: [], markers: [] });
    pick("i1", "i2", "i3");
    connect("i2", "slot");
    await settle();
    expect(links(view.latest())).toEqual(["i2->slot"]);
  });

  it("从没选中的一格拉:也只连它自己", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600), slot], edges: [], markers: [] });
    pick("i1", "i2");
    connect("i3", "slot");
    await settle();
    expect(links(view.latest())).toEqual(["i3->slot"]);
  });
});

/** 从 `nodeId` 的出口(或入口)拉出来,松手在屏幕上一块空白处。 */
function release(nodeId: string, handle: "source" | "target" = "source") {
  const state = {
    isValid: false,
    from: { x: 0, y: 0 },
    fromHandle: { id: null, nodeId, type: handle, position: handle === "source" ? "right" : "left", x: 0, y: 0, width: 8, height: 8 },
    fromPosition: handle === "source" ? "right" : "left",
    fromNode: { id: nodeId },
    to: { x: 500, y: 500 },
    toHandle: null,
    toPosition: null,
    toNode: null,
    pointer: { x: 500, y: 500 },
  } as unknown as FinalConnectionState;
  act(() => {
    flow.props!.onConnectEnd!(new MouseEvent("mouseup", { clientX: 500, clientY: 500 }), state);
  });
}
const menu = () => document.querySelector<HTMLElement>("[data-pending-link-menu]");
const menuItems = () => [...document.querySelectorAll<HTMLButtonElement>('[data-pending-link-menu] [role="menuitem"]')].map((one) => one.textContent ?? "");
const choose = (label: string) =>
  act(() => [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((one) => one.textContent?.includes(label))!.click());

describe("格子自己的出口拉到空白处", () => {
  it("在一组选中的格子里:新建的那一格也只连它自己,单子标题是单格的那一句", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600)], edges: [], markers: [] });
    pick("i1", "i2", "i3");
    release("i2");
    expect(menu()?.textContent).toContain("boardSpawnTitle");
    expect(menu()?.textContent).not.toContain("boardSpawnTitleMany");
    choose("boardKindVideo");
    await settle();
    const made = view.latest().items.find((one) => one.kind === "video")!;
    expect(links(view.latest())).toEqual([`i2->${made.id}`]);
  });

  it("只选了一格:照旧只连它自己,单子标题是单格的那一句", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300)], edges: [], markers: [] });
    pick("i1");
    release("i1");
    expect(menu()?.textContent).toContain("boardSpawnTitle");
    expect(menu()?.textContent).not.toContain("boardSpawnTitleMany");
    choose("boardKindNote");
    await settle();
    const made = view.latest().items.find((one) => one.kind === "note")!;
    expect(links(view.latest())).toEqual([`i1->${made.id}`]);
  });

  it("单子上只列连得上的:从时间线格的入口拉出来,只有视频 / 图片 / 音频", async () => {
    const timeline: BoardItem = { id: "t", kind: "sequence", x: 900, y: 0, width: 560, height: 400, sequence_id: "seq", form: { producer: "sequence_export" } };
    editor.getSequence.mockResolvedValue({ id: "seq", project_id: "p", width: 1920, height: 1080, tracks: [] });
    await mount({ items: [timeline], edges: [], markers: [] });
    release("t", "target");
    const listed = menuItems().join("|");
    expect(listed).toContain("boardKindVideo");
    expect(listed).toContain("boardKindImage");
    expect(listed).toContain("boardKindAudio");
    expect(listed).not.toContain("boardKindNote");
    expect(listed).not.toContain("boardKindDocument");
  });
});

