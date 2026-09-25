/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Edge, FinalConnectionState, Node, ReactFlowInstance, ReactFlowProps } from "@xyflow/react";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

//: 在 jsdom 里走不通一次真的拖线(接点要先被 ResizeObserver 量出位置)。所以只在
//: React Flow 外面包一层,记下画布交给它的 props 和实例 —— 松手那一下直接调画布自己的
//: onConnectEnd,断言看的是画布交给 React Flow 的节点/连线和真实的 DOM。
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

import type { BoardCanvas as Canvas } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { PENDING_EDGE_ID, PENDING_GHOST_ID } from "@/components/app/canvasPendingLink";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";
import { DEFAULT_SIZE } from "@/features/boards/boardNodes";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  flow.props = null;
  flow.instance = null;
});

afterEach(() => {
  vi.useRealTimers();
});

async function mount(canvas: Canvas, extra: Partial<React.ComponentProps<typeof BoardCanvas>> = {}) {
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
            onGenerate={async () => undefined}
            onReady={(next) => {
              api = next;
            }}
            {...extra}
          />
        </div>
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  //: React Flow 的 onInit 是 setTimeout 出来的 —— 不推一下,画布拿不到实例,松手换算不了坐标。
  await settle(10);
  return { api: () => api as unknown as BoardCanvasApi, changes, latest: () => changes[changes.length - 1] };
}

const note = (id: string, x = 0, y = 0) => ({ id, kind: "note" as const, x, y, width: 220, height: 140, color: "yellow" as const, text: "一段字" });
const board: Canvas = { items: [note("n1")], edges: [], markers: [] };

/** 画布这一轮交给 React Flow 的节点 / 连线。 */
const shownNodes = () => (flow.props?.nodes ?? []) as Node[];
const shownEdges = () => (flow.props?.edges ?? []) as Edge[];
const ghost = () => shownNodes().find((node) => node.id === PENDING_GHOST_ID);
const pendingEdge = () => shownEdges().find((edge) => edge.id === PENDING_EDGE_ID);
const menu = () => document.querySelector<HTMLElement>('[data-pending-link-menu]');
const item = (label: string) =>
  [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((one) => one.textContent?.includes(label))!;

async function settle(ms = 500) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** 从 n1 的某一侧接点拉出来,松手在屏幕上 (clientX, clientY) —— 那儿什么都没有。 */
function release(clientX: number, clientY: number, handle: "source" | "target" = "source") {
  const state = {
    isValid: false,
    from: { x: 0, y: 0 },
    fromHandle: { id: null, nodeId: "n1", type: handle, position: handle === "source" ? "right" : "left", x: 0, y: 0, width: 8, height: 8 },
    fromPosition: handle === "source" ? "right" : "left",
    fromNode: { id: "n1" },
    to: { x: clientX, y: clientY },
    toHandle: null,
    toPosition: null,
    toNode: null,
    pointer: { x: clientX, y: clientY },
  } as unknown as FinalConnectionState;
  act(() => {
    flow.props!.onConnectEnd!(new MouseEvent("mouseup", { clientX, clientY }), state);
  });
}

/** 把视口摆成平移 (40, 20)、缩放 0.5 —— 松手点换算成流坐标就不是原样,缩放也一并验了。 */
async function zoomOut() {
  await act(async () => {
    await flow.instance!.setViewport({ x: 40, y: 20, zoom: 0.5 });
  });
}

describe("拉线松手在空白处:占位 + 待定的线 + 单子", () => {
  it("占位落在松手点,大小就是新节点的默认大小;换高亮就换成那一种的大小,线头那一边不动", async () => {
    await mount(board);
    await zoomOut();
    release(300, 200);

    //: (300 - 40) / 0.5 = 520,(200 - 20) / 0.5 = 360。从出口拉出来:左边中点钉在松手点上。
    const image = DEFAULT_SIZE.image;
    expect(ghost()).toMatchObject({ position: { x: 520, y: 360 - image.height / 2 }, width: image.width, height: image.height });
    expect(document.querySelector(`[data-id="${PENDING_GHOST_ID}"] [data-pending-link-ghost]`)).not.toBeNull();

    act(() => {
      item("boardKindVideo").dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
      item("boardKindVideo").focus();
    });
    const video = DEFAULT_SIZE.video;
    expect(ghost()).toMatchObject({ position: { x: 520, y: 360 - video.height / 2 }, width: video.width, height: video.height });
  });

  it("待定的线是一条真边:走线跟着画布的偏好,箭头和实线同一种,从起手那一格接到占位上", async () => {
    await mount({ ...board, items: [note("n1"), note("n2", 400)], edges: [{ id: "e1", source: "n1", target: "n2" }] }, { edgeShape: "smoothstep" });
    release(300, 400);

    const real = shownEdges().find((edge) => edge.id === "e1")!;
    const pending = pendingEdge()!;
    expect(pending).toMatchObject({ source: "n1", target: PENDING_GHOST_ID, type: "smoothstep" });
    expect(real.type).toBe("smoothstep");
    expect((pending.markerEnd as { type: string }).type).toBe((real.markerEnd as { type: string }).type);
    //: 虚线说明「还没定」。
    expect(pending.style?.strokeDasharray).toBeTruthy();
  });

  it("单子打开时焦点在第一项;↓ 换高亮、回车选定 —— 节点落在占位那儿、连好线,撤销历史只多一步", async () => {
    const view = await mount(board);
    await zoomOut();
    release(300, 200);
    const menuItems = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
    expect(document.activeElement).toBe(menuItems[0]);

    act(() => {
      menu()!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    });
    expect(document.activeElement).toBe(menuItems[1]);
    const placed = { ...ghost()!.position };

    act(() => {
      menu()!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    await settle();

    const saved = view.latest();
    const created = saved.items.find((one) => one.id !== "n1")!;
    expect(created).toMatchObject({ kind: "video", x: placed.x, y: placed.y, ...DEFAULT_SIZE.video });
    expect(saved.edges).toEqual([expect.objectContaining({ source: "n1", target: created.id })]);
    expect(ghost()).toBeUndefined();
    expect(pendingEdge()).toBeUndefined();
    expect(menu()).toBeNull();

    //: 一步:撤一下就回到拉线之前,再没有可撤的。
    expect(view.api().canUndo).toBe(true);
    act(() => view.api().undo());
    await settle();
    expect(view.latest().items.map((one) => one.id)).toEqual(["n1"]);
    expect(view.latest().edges).toEqual([]);
    expect(view.api().canUndo).toBe(false);
  });

  it("Esc 取消:占位和待定的线一起消失,什么都没存、历史里没有这一步", async () => {
    const view = await mount(board);
    release(300, 200);
    await settle();
    expect(ghost()).toBeDefined();

    act(() => {
      document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    await settle();

    expect(ghost()).toBeUndefined();
    expect(pendingEdge()).toBeUndefined();
    expect(menu()).toBeNull();
    expect(document.querySelector(`[data-id="${PENDING_GHOST_ID}"]`)).toBeNull();
    //: 占位从头到尾没进过要存的那一份。
    for (const canvas of view.changes) {
      expect(canvas.items.map((one) => one.id)).toEqual(["n1"]);
      expect(canvas.edges).toEqual([]);
    }
    expect(view.api().canUndo).toBe(false);
  });

  it("点别处取消;点单子里面不取消", async () => {
    await mount(board);
    release(300, 200);
    act(() => {
      menu()!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    });
    expect(ghost()).toBeDefined();

    act(() => {
      document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    });
    expect(ghost()).toBeUndefined();
    expect(menu()).toBeNull();
  });

  it("从左边的入口拉出来:占位的右边中点落在松手点,线从占位接回起手那一格", async () => {
    const view = await mount(board);
    await zoomOut();
    release(20, 200, "target");

    const image = DEFAULT_SIZE.image;
    //: (20 - 40) / 0.5 = -40。
    expect(ghost()).toMatchObject({ position: { x: -40 - image.width, y: 360 - image.height / 2 }, width: image.width });
    expect(pendingEdge()).toMatchObject({ source: PENDING_GHOST_ID, target: "n1" });

    act(() => item("boardKindNote").click());
    await settle();
    const created = view.latest().items.find((one) => one.id !== "n1")!;
    expect(created).toMatchObject({ kind: "note", x: -40 - DEFAULT_SIZE.note.width, y: 360 - DEFAULT_SIZE.note.height / 2 });
    expect(view.latest().edges).toEqual([expect.objectContaining({ source: created.id, target: "n1" })]);
  });

  it("连到了别的接点上(isValid)不弹 —— 那是一次正常连线", async () => {
    await mount(board);
    act(() => {
      flow.props!.onConnectEnd!(new MouseEvent("mouseup", { clientX: 1, clientY: 1 }), {
        isValid: true,
        fromNode: { id: "n1" },
        fromHandle: { id: null, type: "source" },
      } as unknown as FinalConnectionState);
    });
    expect(ghost()).toBeUndefined();
    expect(menu()).toBeNull();
  });
});
