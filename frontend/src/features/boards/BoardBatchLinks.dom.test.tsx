/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Connection, FinalConnectionState, ReactFlowInstance, ReactFlowProps } from "@xyflow/react";

/**
 * 多选之后一次连线(TapNow 那样:框选几格,从其中一格拉到目标,这几格都连过去)、多选之后拉出来新建一格。
 *
 * jsdom 里走不通一次真的拖线(接点要 ResizeObserver 量出位置),所以和 BoardPendingLink 的测试一样:在 React Flow
 * 外面包一层记下画布交给它的 props,直接调画布自己的 onConnect / onConnectEnd,断言看画布汇出的画布和撤销。
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
  return { api: () => api as unknown as BoardCanvasApi, latest: () => changes.at(-1) ?? canvas };
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

describe("多选之后一次连到一格", () => {
  it("选中三张图,从其中一张拉到生成格:三张都连过去;撤一下三根一起没了", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600), slot], edges: [], markers: [] });
    pick("i1", "i2", "i3");
    connect("i2", "slot");
    await settle();
    expect(links(view.latest())).toEqual(["i1->slot", "i2->slot", "i3->slot"]);
    expect(toastMocks.error).not.toHaveBeenCalled();

    act(() => view.api().undo());
    await settle();
    expect(view.latest().edges).toEqual([]);
  });

  it("从没选中的一格拉:只连它自己,选中的那几格不跟着", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600), slot], edges: [], markers: [] });
    pick("i1", "i2");
    connect("i3", "slot");
    await settle();
    expect(links(view.latest())).toEqual(["i3->slot"]);
  });

  it("连不上的跳过(便签进不了时间线格、已经连着的),说一声几条没连上;连得上的接到时间线末尾,撤一下线和片段一起回去", async () => {
    editor.appendAssetToSequence.mockResolvedValueOnce({ id: "seq", tracks: [], revision: 7 }).mockResolvedValueOnce({ id: "seq", tracks: [], revision: 8 });
    editor.undoSequence.mockResolvedValueOnce({ id: "seq", tracks: [], revision: 9 }).mockResolvedValueOnce({ id: "seq", tracks: [], revision: 10 });
    const note: BoardItem = { id: "n1", kind: "note", x: 0, y: 300, width: 220, height: 140, text: "旁白" };
    const timeline: BoardItem = { id: "t", kind: "sequence", x: 900, y: 0, width: 560, height: 400, sequence_id: "seq", form: { producer: "sequence_export" } };
    const view = await mount({
      items: [image("i1", 0), image("i2", 300), image("i3", 600), note, timeline],
      edges: [{ id: "old", source: "i3", target: "t" }],
      markers: [],
    });
    pick("i1", "i2", "i3", "n1");
    connect("i1", "t");
    await settle();
    await settle();
    expect(links(view.latest())).toEqual(["i1->t", "i2->t", "i3->t"]);
    expect(toastMocks.error).toHaveBeenCalledWith("boardLinksRefused");
    expect(editor.appendAssetToSequence.mock.calls, "一段一段接,不并发").toEqual([["seq", "a-i1"], ["seq", "a-i2"]]);

    act(() => view.api().undo());
    await settle();
    expect(links(view.latest()), "两根新线一起撤掉").toEqual(["i3->t"]);
    expect(editor.undoSequence.mock.calls, "时间线上接的两段也一起撤,一次接一次").toEqual([["seq", 8], ["seq", 9]]);
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

describe("多选之后拉出来新建一格", () => {
  it("选中三张图,从其中一张拉出来松手:新建的那一格把三张都连上;撤一下格子和三根线一起没了", async () => {
    const view = await mount({ items: [image("i1", 0), image("i2", 300), image("i3", 600)], edges: [], markers: [] });
    pick("i1", "i2", "i3");
    release("i2");
    expect(menu()?.textContent).toContain("boardSpawnTitleMany");
    choose("boardKindVideo");
    await settle();
    const made = view.latest().items.find((one) => one.kind === "video")!;
    expect(made).toBeDefined();
    expect(links(view.latest())).toEqual([`i1->${made.id}`, `i2->${made.id}`, `i3->${made.id}`]);

    act(() => view.api().undo());
    await settle();
    expect(view.latest().items.map((one) => one.id)).toEqual(["i1", "i2", "i3"]);
    expect(view.latest().edges).toEqual([]);
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

