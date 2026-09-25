/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 画板详情页和服务端之间的那段同步:自动保存、画布上的动作(生成/写字/念/截)、轮询回执。
 *
 * 画布本身换成一个桩 —— 这里要钉的是**详情页怎么和服务端说话**,不是 React Flow 怎么画。
 */

const apiMocks = vi.hoisted(() => ({
  listBoards: vi.fn(),
  getBoard: vi.fn(),
  updateBoard: vi.fn(),
  generateOnBoard: vi.fn(),
  writeOnBoard: vi.fn(),
  listComments: vi.fn(),
  listMembers: vi.fn(),
  api: vi.fn(),
}));
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const canvasHarness = vi.hoisted(() => ({
  props: null as null | Record<string, unknown>,
  api: {
    add: vi.fn(),
    patch: vi.fn(),
    replace: vi.fn(),
    fitView: vi.fn(),
    focusComment: vi.fn(),
    focusItem: vi.fn(),
    markers: [],
    addMarker: vi.fn(),
    jumpToMarker: vi.fn(),
    undo: vi.fn(),
    redo: vi.fn(),
    canUndo: false,
    canRedo: false,
  },
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));
vi.mock("sonner", () => ({ toast: toastMocks }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));
vi.mock("@/features/collaboration/CollaborationSheet", () => ({ CollaborationSheet: () => null }));
vi.mock("@/features/scenes/ScenePickerDialog", () => ({ ScenePickerDialog: () => null }));
vi.mock("@/features/boards/AssetPickerDialog", () => ({ AssetPickerDialog: () => null }));
vi.mock("@/features/boards/BoardCanvas", () => ({
  BoardCanvas: (props: Record<string, unknown>) => {
    canvasHarness.props = props;
    React.useEffect(() => {
      (props.onReady as (api: unknown) => void)(canvasHarness.api);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return null;
  },
}));

import type { Board, BoardCanvas, Workspace } from "@/api/client";
import { BoardsView } from "@/features/boards/BoardsView";

const workspace = { id: "w1", name: "W" } as Workspace;

function boardAt(revision: number, canvas: BoardCanvas): Board {
  return {
    id: "b1",
    workspace_id: "w1",
    name: "灵感",
    canvas,
    revision,
    created_at: "2026-09-20T00:00:00",
    updated_at: "2026-09-20T00:00:00",
  } as Board;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BoardsView workspace={workspace} />
    </QueryClientProvider>,
  );
}

const props = () => canvasHarness.props as {
  onChange: (canvas: BoardCanvas) => void;
  onGenerate: (input: Record<string, unknown>) => Promise<unknown>;
  onWrite: (input: Record<string, unknown>) => Promise<unknown>;
};

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  localStorage.clear();
  localStorage.setItem("mosael:selected:boards:w1", "b1");
  canvasHarness.props = null;
  Object.values(apiMocks).forEach((mock) => mock.mockReset());
  Object.values(canvasHarness.api).forEach((one) => typeof one === "function" && (one as ReturnType<typeof vi.fn>).mockReset());
  toastMocks.error.mockReset();
  apiMocks.listComments.mockResolvedValue([]);
  apiMocks.listMembers.mockResolvedValue({ members: [] });
  apiMocks.api.mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("画板详情页与服务端的同步", () => {
  it("字段顺序不同但内容一样的画布不算本地改动 —— 回执落地时直接采用服务端那份,不撞出一次假冲突", async () => {
    // 服务端的项按 normalize 的顺序写字段;本地新建后才写字的便签,text 排在 color 后面。
    const server: BoardCanvas = {
      items: [
        { id: "n1", kind: "note", x: 0, y: 0, width: 220, height: 140, text: "一只猫", color: "yellow" },
        { id: "img", kind: "image", x: 300, y: 0, width: 260, height: 180, run: { status: "running", job_id: "job-1" } },
      ],
      edges: [],
      markers: [],
    };
    const local: BoardCanvas = {
      items: [
        { id: "n1", kind: "note", x: 0, y: 0, width: 220, height: 140, color: "yellow", text: "一只猫" },
        server.items[1],
      ],
      edges: [],
      markers: [],
    };
    const settled: BoardCanvas = {
      ...server,
      items: [server.items[0], { ...server.items[1], asset_id: "a1", run: { status: "succeeded" } }],
    };
    apiMocks.listBoards.mockResolvedValue([boardAt(3, server)]);
    apiMocks.updateBoard.mockResolvedValue(boardAt(3, server));
    apiMocks.getBoard.mockResolvedValue(boardAt(4, settled));

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange(local));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(apiMocks.getBoard).toHaveBeenCalled();
    expect(canvasHarness.api.replace).toHaveBeenCalledWith(settled);
    expect(toastMocks.error).not.toHaveBeenCalled();
  });

  it("存回去的是撤销后的空槽,服务端留住了在跑的任务 —— 本地那一格跟着回到「在跑」", async () => {
    // 运行态归服务端(见后端 _keep_server_owned_state)。服务端没收客户端那份运行态时,本地
    // 还是一个能点的空槽:用户以为没点中又点一次,而第一轮还在跑。
    const running = { id: "img", kind: "image" as const, x: 0, y: 0, width: 260, height: 180, run: { status: "running" as const, job_id: "job-1" } };
    const server: BoardCanvas = { items: [running], edges: [], markers: [] };
    const undone: BoardCanvas = { items: [{ id: "img", kind: "image", x: 40, y: 0, width: 260, height: 180 }], edges: [], markers: [] };
    apiMocks.listBoards.mockResolvedValue([boardAt(3, server)]);
    apiMocks.updateBoard.mockResolvedValue(boardAt(4, { ...server, items: [{ ...running, x: 40 }] }));
    apiMocks.getBoard.mockReturnValue(new Promise(() => undefined));

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange(undone));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });

    expect(apiMocks.updateBoard).toHaveBeenCalledTimes(1);
    expect(canvasHarness.api.patch).toHaveBeenCalledWith("img", expect.objectContaining({ run: { status: "running", job_id: "job-1" } }));
  });

  it("一直在拖的时候,在跑的那一格照样按时轮询到产出 —— 不等人停手", async () => {
    const running = { id: "img", kind: "image" as const, x: 0, y: 0, width: 260, height: 180, run: { status: "running" as const, job_id: "job-1" } };
    const note = { id: "n1", kind: "note" as const, x: 400, y: 0, width: 220, height: 140, text: "拖着我" };
    const server: BoardCanvas = { items: [running, note], edges: [], markers: [] };
    const settled = { ...running, asset_id: "a1", run: { status: "succeeded" as const } };
    apiMocks.listBoards.mockResolvedValue([boardAt(3, server)]);
    apiMocks.updateBoard.mockImplementation(async (_id: string, body: { canvas: BoardCanvas }) => boardAt(4, body.canvas));
    apiMocks.getBoard.mockResolvedValue(boardAt(5, { ...server, items: [settled, note] }));

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    // 每 0.5 秒拖一下,拖满 6 秒 —— 比轮询的间隔长得多。
    for (let step = 1; step <= 12; step += 1) {
      act(() => props().onChange({ ...server, items: [running, { ...note, x: 400 + step * 10 }] }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });
    }

    expect(apiMocks.getBoard).toHaveBeenCalled();
    expect(canvasHarness.api.patch).toHaveBeenCalledWith("img", expect.objectContaining({ asset_id: "a1" }));
  });

  it("刚在便签上敲完字就点「改写」:先把这段字存上,改写照着眼前这段来", async () => {
    // 服务端从它那份画布上读便签现在的字。自动保存还在 600ms 防抖里时就发改写,读到的是上一版。
    const server: BoardCanvas = {
      items: [{ id: "n1", kind: "note", x: 0, y: 0, width: 220, height: 140, text: "旧的那段" }],
      edges: [],
      markers: [],
    };
    const typed: BoardCanvas = { ...server, items: [{ ...server.items[0], text: "刚敲完的这段" }] };
    const order: string[] = [];
    apiMocks.listBoards.mockResolvedValue([boardAt(3, server)]);
    apiMocks.updateBoard.mockImplementation(async (_id: string, body: { canvas: BoardCanvas }) => {
      order.push(`save:${body.canvas.items[0].text}`);
      return boardAt(4, body.canvas);
    });
    apiMocks.writeOnBoard.mockImplementation(async (_id: string, body: { base_revision: number }) => {
      order.push(`write@${body.base_revision}`);
      return boardAt(5, { ...typed, items: [{ ...typed.items[0], text: "改好的", run: { status: "succeeded" } }] });
    });

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange(typed));
    await act(async () => {
      await props().onWrite({ itemId: "n1", prompt: "短一点", providerProfileId: "p", model: "m", assets: [], context: [] });
    });

    expect(order).toEqual(["save:刚敲完的这段", "write@4"]);
  });

  it("自动保存还在路上时点生成:生成等它回来,带着它换来的新版本号,不和自己撞 409", async () => {
    const server: BoardCanvas = {
      items: [{ id: "img", kind: "image", x: 0, y: 0, width: 260, height: 180 }],
      edges: [],
      markers: [],
    };
    const moved: BoardCanvas = { ...server, items: [{ ...server.items[0], x: 40 }] };
    const save = deferred<Board>();
    apiMocks.listBoards.mockResolvedValue([boardAt(3, server)]);
    apiMocks.updateBoard.mockReturnValue(save.promise);
    apiMocks.generateOnBoard.mockResolvedValue(
      boardAt(5, { ...moved, items: [{ ...moved.items[0], run: { status: "running", job_id: "job-1" } }] }),
    );

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange(moved));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });
    expect(apiMocks.updateBoard).toHaveBeenCalledTimes(1);

    let generating: Promise<unknown> = Promise.resolve();
    act(() => {
      generating = props().onGenerate({ kind: "image", prompt: "一只猫", itemId: "img" });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(apiMocks.generateOnBoard).not.toHaveBeenCalled();

    await act(async () => {
      save.resolve(boardAt(4, moved));
      await generating;
    });
    expect(apiMocks.generateOnBoard).toHaveBeenCalledTimes(1);
    expect(apiMocks.generateOnBoard.mock.calls[0][1]).toMatchObject({ base_revision: 4, item_id: "img" });
  });
});
