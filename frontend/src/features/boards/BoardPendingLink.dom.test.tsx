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

//: 单子的定位交给 floating-ui。jsdom 里没有布局、也不会自己一帧一帧地跑,所以只接管**这张单子**
//: 的那两步:autoUpdate 把「下一帧」攒起来由测试手动推(frame()),computePosition 记下这一帧
//: 用的参照矩形,并把单子贴在参照的右上角 —— 断言看的是「参照换没换」,而不是 floating-ui 本身。
const placement = { frames: new Set<() => void>(), references: [] as { left: number; top: number; right: number; bottom: number }[] };
vi.mock("@floating-ui/dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@floating-ui/dom")>();
  const ours = (el: unknown) => el instanceof HTMLElement && el.hasAttribute("data-pending-link-menu");
  return {
    ...actual,
    autoUpdate: ((reference, floating, update, options) => {
      if (!ours(floating)) return actual.autoUpdate(reference, floating, update, options);
      placement.frames.add(update);
      update();
      return () => placement.frames.delete(update);
    }) satisfies typeof actual.autoUpdate,
    computePosition: (async (reference, floating, options) => {
      if (!ours(floating)) return actual.computePosition(reference, floating, options);
      const rect = reference.getBoundingClientRect();
      placement.references.push(rect);
      return { x: rect.right + 12, y: rect.top, placement: options?.placement ?? "right", strategy: "fixed", middlewareData: {} };
    }) satisfies typeof actual.computePosition,
  };
});

import type { BoardCanvas as Canvas } from "@/api/client";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { PENDING_EDGE_ID, PENDING_GHOST_ID } from "@/components/app/canvasPendingLink";
import { CANVAS_EDGE_OPTIONS, canvasEdgeClass } from "@/components/app/canvasEdges";
import { BoardCanvas, type BoardCanvasApi } from "@/features/boards/BoardCanvas";
import { DEFAULT_SIZE } from "@/features/boards/boardNodes";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  flow.props = null;
  flow.instance = null;
  placement.frames.clear();
  placement.references = [];
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
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
            onRun={async () => undefined}
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

/** 指针移到某一行上:先 pointerover(进了这一行),再 pointermove —— 真机上两个都会来。 */
function hover(label: string) {
  act(() => {
    item(label).dispatchEvent(new PointerEvent("pointerover", { bubbles: true }));
    item(label).dispatchEvent(new PointerEvent("pointermove", { bubbles: true }));
  });
}

/** 推一帧:跑一遍单子的定位,等它把位置写上。 */
async function frame() {
  await act(async () => {
    for (const update of placement.frames) update();
    await Promise.resolve();
    await Promise.resolve();
  });
}

/**
 * 把视口摆成平移 (40, 20)、缩放 0.5 —— 松手点换算成流坐标就不是原样,缩放也一并验了。
 *
 * **摆上了才算数。** CI 上文件里的第一条用例(冷启动、机器慢)松手换算出了 NaN 的位置,错却报在
 * 后面「占位在哪」的断言上 —— 画布这时的视口不是这一份(平移缩放器还没装好:setViewport 没生效,
 * 或者对着还没量出尺寸的画布算出了 NaN)。所以一直推到视口真是这一份为止;推不到就在这里说清
 * 是视口没摆上,而不是让一个 NaN 流到后面去。
 */
async function zoomOut() {
  const target = { x: 40, y: 20, zoom: 0.5 };
  for (let attempt = 0; attempt < 50; attempt += 1) {
    await act(async () => {
      await flow.instance!.setViewport(target);
    });
    const now = flow.instance!.getViewport();
    if (now.x === target.x && now.y === target.y && now.zoom === target.zoom) return;
    await settle(10);
  }
  expect(flow.instance!.getViewport(), "视口一直没摆上 —— 画布的平移缩放器没装好").toEqual(target);
}

describe("拉线松手在空白处:占位 + 待定的线 + 单子", () => {
  it("占位落在松手点,换高亮只换图标和名字、大小不变;选定后真节点按自己的大小落下,线头那一边不动", async () => {
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
    //: 选的时候什么都不动:占位还是原来那块,只是换成视频的图标。
    expect(ghost()).toMatchObject({ position: { x: 520, y: 360 - image.height / 2 }, width: image.width, height: image.height });
    expect(ghost()?.data).toMatchObject({ label: "boardKindVideo" });
  });

  it("待定的线是一条真边:走线跟着画布的偏好,箭头和实线同一种,从起手那一格接到占位上", async () => {
    await mount({ ...board, items: [note("n1"), note("n2", 400)], edges: [{ id: "e1", source: "n1", target: "n2" }] }, { edgeShape: "smoothstep" });
    release(300, 400);

    const real = shownEdges().find((edge) => edge.id === "e1")!;
    const pending = pendingEdge()!;
    expect(pending).toMatchObject({ source: "n1", target: PENDING_GHOST_ID, type: "smoothstep" });
    expect(real.type).toBe("smoothstep");
    //: 箭头**就是**实线那一个(它取线自己的颜色),不是另造一个主色的。
    expect(pending.markerEnd).toEqual(real.markerEnd);
    //: 「待定」那一种:主色静止虚线(样子在 canvasEdges 的类里,不是行内 style)。
    expect(pending.className).toBe(canvasEdgeClass("pending"));
    expect(pending.style).toBeUndefined();
    //: 和占位同一层,压在已有的项之上 —— 否则穿过别的卡片时就看不出它接到哪儿了。
    expect(pending.zIndex).toBe(ghost()!.zIndex);
    expect(pending.zIndex!).toBeGreaterThan(shownNodes().find((node) => node.id === "n2")!.zIndex!);
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
    //: 真节点按视频自己的大小落下:线头那一侧(左边)和占位同一条边,竖直方向仍以松手点为中线。
    const middle = placed.y + DEFAULT_SIZE.image.height / 2;
    expect(created).toMatchObject({ kind: "video", x: placed.x, y: middle - DEFAULT_SIZE.video.height / 2, ...DEFAULT_SIZE.video });
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

  it("换高亮时占位和单子都纹丝不动 —— 否则单子一挪,指针底下换了一行,高亮又变,来回闪", async () => {
    //: jsdom 没有布局:把占位节点的 DOM 矩形按它在画布上的位置、大小和视口算出来,和浏览器里一样。
    const layout = Element.prototype.getBoundingClientRect;
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const node = ghost();
      if (node && flow.instance && this.matches(`.react-flow__node[data-id="${PENDING_GHOST_ID}"]`)) {
        const { x, y, zoom } = flow.instance.getViewport();
        return new DOMRect(node.position.x * zoom + x, node.position.y * zoom + y, node.width! * zoom, node.height! * zoom);
      }
      return layout.call(this);
    });
    await mount(board);
    await zoomOut();
    release(300, 200);
    await frame();
    const menuAt = () => ({ left: menu()!.style.left, top: menu()!.style.top });
    const first = menuAt();
    expect(first.left).not.toBe("");

    for (const label of ["boardKindVideo", "boardKindAudio", "boardKindDocument", "boardKindNote", "boardKindImage"]) {
      hover(label);
      await frame();
      expect(menuAt()).toEqual(first);
      //: 单子贴的就是占位本身那块地方 —— 占位不变大小,参照也就不变。
      const reference = placement.references.at(-1)!;
      const { x, y, zoom } = flow.instance!.getViewport();
      const node = ghost()!;
      expect(node).toMatchObject(DEFAULT_SIZE.image);
      expect(reference.left).toBeCloseTo(node.position.x * zoom + x);
      expect(reference.top).toBeCloseTo(node.position.y * zoom + y);
      expect(reference.right - reference.left).toBeCloseTo(node.width! * zoom);
      expect(reference.bottom - reference.top).toBeCloseTo(node.height! * zoom);
    }
  });

  it("高亮只有一处:指针移到哪一行就是哪一行(焦点也跟过去),方向键接着从它往下走;移出单子留在最后那一行", async () => {
    await mount(board);
    release(300, 200);
    const rows = () => [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')];
    const highlighted = () => rows().filter((row) => row.hasAttribute("data-highlighted"));

    hover("boardKindAudio");
    expect(highlighted()).toEqual([item("boardKindAudio")]);
    expect(document.activeElement).toBe(item("boardKindAudio"));
    expect(ghost()).toMatchObject(DEFAULT_SIZE.image);
    expect(ghost()?.data).toMatchObject({ label: "boardKindAudio" });

    act(() => {
      menu()!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    });
    expect(highlighted()).toEqual([item("boardKindNote")]);
    expect(document.activeElement).toBe(item("boardKindNote"));
    expect(ghost()?.data).toMatchObject({ label: "boardKindNote" });

    act(() => {
      menu()!.dispatchEvent(new PointerEvent("pointerout", { bubbles: true }));
      menu()!.dispatchEvent(new PointerEvent("pointerleave"));
    });
    expect(highlighted()).toEqual([item("boardKindNote")]);
    expect(ghost()?.data).toMatchObject({ label: "boardKindNote" });

    //: 只有一种画法:没有 hover:/focus: 的底色另画一行,图标也不会只在高亮时多出一圈描边。
    for (const row of rows()) {
      expect(row.className).not.toMatch(/(^|\s)(hover|focus):bg-/);
      expect(row.querySelector('[class*="border"]')).toBeNull();
    }
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

describe("画板连线的层次与外观", () => {
  it("连线夹在分组框和项之间:画在框的底色和虚线边框之上,两头钻进卡片底下", async () => {
    const frame = { id: "f1", kind: "frame" as const, x: -40, y: -40, width: 800, height: 400 };
    await mount({ items: [frame, note("n1"), note("n2", 400)], edges: [{ id: "e1", source: "n1", target: "n2" }], markers: [] });

    const z = (id: string) => shownNodes().find((node) => node.id === id)!.zIndex!;
    const edge = shownEdges().find((one) => one.id === "e1")!;
    expect(edge.zIndex!).toBeGreaterThan(z("f1"));
    expect(edge.zIndex!).toBeLessThan(z("n1"));
    expect(edge.zIndex!).toBeLessThan(z("n2"));
    //: 选中的线也不许浮到卡片上面去(React Flow 的 elevateEdgesOnSelect 会给它加 1000)。
    expect(flow.props?.elevateEdgesOnSelect).not.toBe(true);
  });

  it("每条线都带共用的箭头和命中带;画出来的样子不写进画布数据", async () => {
    const view = await mount({ items: [note("n1"), note("n2", 400)], edges: [{ id: "e1", source: "n1", target: "n2" }], markers: [] });

    const edge = shownEdges().find((one) => one.id === "e1")!;
    expect(edge.markerEnd).toBe(CANVAS_EDGE_OPTIONS.markerEnd);
    expect(edge.interactionWidth).toBe(CANVAS_EDGE_OPTIONS.interactionWidth);
    //: 画板的线就是「引用」那一种:不挂任何变体类,颜色吃容器上的默认线色。
    expect(edge.className).toBeUndefined();
    await settle(10);
    expect(view.latest()?.edges).toEqual([{ id: "e1", source: "n1", target: "n2" }]);
  });
});

describe("拉线菜单里只有格子", () => {
  //: 形状和 GET /api/boards/producers 发下来的一样。能力住在内容格上(选中一格,在操作条上点),不在拉线菜单里。
  const producer = (id: string, label: string, extra: Record<string, unknown> = {}) =>
    ({
      id, type: id.replace(/^node:/, ""), label, description: `${label}的说明`, category: "工作流里的分组", config: {}, outputs: [],
      output_types: {}, output_labels: {}, plugin_name: "", tool_name: "", body_scope: {}, hosts: ["note", "document"],
      role: "ability", host_fields: { note: "text", document: "text" },
      permission: "edit", effects: "none", fills_empty_slot: false,
      board_group: "text", board_group_label: "处理文字", board_description: `${label}一句话`, ...extra,
    }) as unknown as NonNullable<React.ComponentProps<typeof BoardCanvas>["producers"]>[number];
  const producers = [
    producer("write", "写字", { hosts: ["note"], role: "slot", fills_empty_slot: true }),
    producer("node:translate", "翻译"),
    producer("node:plugin.cut.out", "去背景", { hosts: ["image"], plugin_name: "我的抠图", tool_name: "remove_bg" }),
  ];

  it("拉一根线出来只为了长出一格新的内容:单子上是那几种格子,没有工具、不分组、不给搜索框", async () => {
    await mount(board, { producers });
    release(300, 200);
    const rows = [...document.querySelectorAll('[role="menuitem"]')].map((one) => one.textContent ?? "");
    expect(rows.some((one) => one.includes("翻译") || one.includes("去背景"))).toBe(false);
    expect(rows.length).toBeGreaterThan(0);
    expect(document.querySelector('[data-pending-link-menu] input[type="search"]')).toBeNull();
    expect(document.querySelectorAll("[data-pending-link-group]")).toHaveLength(0);
  });
});
