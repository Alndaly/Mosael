/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render } from "@testing-library/react";
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
  runOnBoard: vi.fn(),
  listBoardProducers: vi.fn(),
  cancelJob: vi.fn(),
  listComments: vi.fn(),
  listMembers: vi.fn(),
  importAsset: vi.fn(),
  api: vi.fn(),
}));
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const canvasHarness = vi.hoisted(() => ({
  props: null as null | Record<string, unknown>,
  api: {
    add: vi.fn(),
    patch: vi.fn(),
    adopt: vi.fn(),
    flush: vi.fn(),
    fitView: vi.fn(),
    focusComment: vi.fn(),
    focusItem: vi.fn(),
    isInView: vi.fn(),
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
const pickerHarness = vi.hoisted(() => ({ props: null as null | Record<string, unknown> }));
vi.mock("@/features/boards/AssetPickerDialog", () => ({
  AssetPickerDialog: (props: Record<string, unknown>) => {
    pickerHarness.props = props;
    return null;
  },
}));
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

import { ApiError, type Board, type BoardCanvas, type Workspace } from "@/api/client";
import { BoardsView } from "@/features/boards/BoardsView";
import { invalidateAfterDecision } from "@/features/agent/confirmationCaches";

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

/**
 * 打开这一张:清单给摘要,画布由详情接口给(第一次 getBoard)。之后测试自己给的 getBoard 是轮询 / 重取拿到的。
 */
function opens(board: Board) {
  apiMocks.listBoards.mockResolvedValue([board]);
  apiMocks.getBoard.mockResolvedValueOnce(board);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

let queryClient: QueryClient;

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient = client;
  return render(
    <QueryClientProvider client={client}>
      <BoardsView workspace={workspace} />
    </QueryClientProvider>,
  );
}

/** 画布最后一次被交过去采用的那份(合好本地改动的服务端新版,见 BoardsView.adoptServer)。 */
const adopted = (): BoardCanvas | undefined => canvasHarness.api.adopt.mock.calls.at(-1)?.[0] as BoardCanvas | undefined;
const adoptedItem = (id: string) => adopted()?.items.find((one) => one.id === id);

const props = () => canvasHarness.props as {
  onChange: (canvas: BoardCanvas) => void;
  onRun: (request: Record<string, unknown>) => Promise<unknown>;
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
  toastMocks.success.mockReset();
  //: 画布桩:新落下的格子默认都看得见(不提示「去看看」)。
  canvasHarness.api.isInView.mockReturnValue(true);
  apiMocks.listComments.mockResolvedValue([]);
  apiMocks.listMembers.mockResolvedValue({ members: [] });
  apiMocks.api.mockResolvedValue([]);
  apiMocks.listBoardProducers.mockResolvedValue([]);
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
    opens(boardAt(3, server));
    apiMocks.updateBoard.mockResolvedValue(boardAt(3, server));
    apiMocks.getBoard.mockResolvedValue(boardAt(4, settled));

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange(local));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(apiMocks.getBoard).toHaveBeenCalled();
    expect(adopted()).toEqual(settled);
    expect(toastMocks.error).not.toHaveBeenCalled();
  });

  it("存回去的是撤销后的空槽,服务端留住了在跑的任务 —— 本地那一格跟着回到「在跑」", async () => {
    // 运行态归服务端(见后端 _keep_server_owned_state)。服务端没收客户端那份运行态时,本地
    // 还是一个能点的空槽:用户以为没点中又点一次,而第一轮还在跑。
    const running = { id: "img", kind: "image" as const, x: 0, y: 0, width: 260, height: 180, run: { status: "running" as const, job_id: "job-1" } };
    const server: BoardCanvas = { items: [running], edges: [], markers: [] };
    const undone: BoardCanvas = { items: [{ id: "img", kind: "image", x: 40, y: 0, width: 260, height: 180 }], edges: [], markers: [] };
    opens(boardAt(3, server));
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
    opens(boardAt(3, server));
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

  it("拖完最后一下就离开画板(画布还攒着没汇上来):那一下照样存上", async () => {
    const note = { id: "n1", kind: "note" as const, x: 0, y: 0, width: 220, height: 140, text: "a" };
    const server: BoardCanvas = { items: [note], edges: [], markers: [] };
    opens(boardAt(3, server));
    apiMocks.updateBoard.mockImplementation(async (_id: string, body: { canvas: BoardCanvas }) => boardAt(4, body.canvas));

    const view = mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    //: 画布此刻:便签拖到了 500,还没到 400ms 的并步,没汇给上层。卸载时上层先停、画布后停。
    canvasHarness.api.flush.mockImplementation(() => ({ ...server, items: [{ ...note, x: 500 }] }));
    view.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });

    expect(apiMocks.updateBoard).toHaveBeenCalledTimes(1);
    expect((apiMocks.updateBoard.mock.calls[0][1] as { canvas: BoardCanvas }).canvas.items[0].x).toBe(500);
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
    opens(boardAt(3, server));
    apiMocks.updateBoard.mockImplementation(async (_id: string, body: { canvas: BoardCanvas }) => {
      order.push(`save:${body.canvas.items[0].text}`);
      return boardAt(4, body.canvas);
    });
    apiMocks.runOnBoard.mockImplementation(async (_id: string, body: { base_revision: number }) => {
      order.push(`write@${body.base_revision}`);
      return boardAt(5, { ...typed, items: [{ ...typed.items[0], text: "改好的", run: { status: "succeeded" } }] });
    });

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange(typed));
    await act(async () => {
      await props().onRun({
        producer: "write", item_id: "n1", kind: "note", x: 0, y: 0,
        form: { prompt: "短一点", provider_profile_id: "p", model: "m", source_assets: [] },
      });
    });

    expect(order).toEqual(["save:刚敲完的这段", "write@4"]);
  });

  it("截挂了的那一格就地重截:本地换的是那一格的运行态,不另加一格同名的", async () => {
    const trim = { asset_id: "src", start: 1, end: 3, mute: false };
    const failed = { id: "cut", kind: "video" as const, x: 0, y: 300, width: 320, height: 200, form: { trim }, run: { status: "failed" as const, error: "截取失败" } };
    const server: BoardCanvas = { items: [failed], edges: [], markers: [] };
    const retried = { ...failed, form: { trim: { ...trim, start: 0.5 } }, run: { status: "running" as const, job_id: "job-2" } };
    opens(boardAt(3, server));
    apiMocks.runOnBoard.mockResolvedValue(boardAt(4, { ...server, items: [retried] }));
    apiMocks.getBoard.mockReturnValue(new Promise(() => undefined));

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    await act(async () => {
      await props().onRun({
        producer: "trim", item_id: "cut", kind: "video", x: 0, y: 300,
        form: { asset_id: "src", start: 0.5, end: 3, mute: false },
      });
    });

    expect(apiMocks.runOnBoard.mock.calls[0][1]).toMatchObject({ item_id: "cut", producer: "trim", form: { asset_id: "src", start: 0.5 } });
    expect(canvasHarness.api.add).not.toHaveBeenCalled();
    expect(adopted()?.items.filter((one) => one.id === "cut")).toHaveLength(1);
    expect(adoptedItem("cut")).toMatchObject({ form: retried.form, run: retried.run });
  });

  it("存不下是因为某一格(字太长):跳到那一格、圈出来,提示说的是「有一格存不下」而不是一个内部 id", async () => {
    const server: BoardCanvas = { items: [{ id: "n-long", kind: "note", x: 0, y: 0, width: 220, height: 140, text: "短" }], edges: [], markers: [] };
    opens(boardAt(3, server));
    apiMocks.updateBoard.mockRejectedValue(
      new ApiError("画板项 n-long 的文字超过 20000 字", 400, JSON.stringify({ detail: "画板项 n-long 的文字超过 20000 字", item_id: "n-long" })),
    );
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange({ ...server, items: [{ ...server.items[0], text: "长".repeat(10) }] }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });

    expect(canvasHarness.api.focusItem).toHaveBeenCalledWith("n-long");
    expect(toastMocks.error).toHaveBeenCalledWith("boardSaveFailedAt", { description: "画板项 n-long 的文字超过 20000 字" });
    expect((canvasHarness.props as { searchHighlight?: { ids: Set<string> } }).searchHighlight?.ids.has("n-long")).toBe(true);
  });

  it("删掉那根线之后存回去:服务端摘掉了从那条线来的那份,本地那一格跟着摘,手动挂的照留", async () => {
    // 「从上游来的那份活得和线一样长」只有后端一处规则(canvas._drop_detached_bindings),前端收它存下的。
    const upstream = { id: "A", kind: "image" as const, x: 0, y: 0, width: 260, height: 180, asset_id: "a1" };
    const fed = { asset_id: "a1", role: "first_frame", from: "A" };
    const manual = { asset_id: "m1", role: "last_frame" };
    const video = { id: "V", kind: "video" as const, x: 400, y: 0, width: 320, height: 200, form: { prompt: "动起来", source_assets: [fed, manual] } };
    const server: BoardCanvas = { items: [upstream, video], edges: [{ id: "e1", source: "A", target: "V" }], markers: [] };
    const unwired: BoardCanvas = { ...server, edges: [] };
    const stored: BoardCanvas = { ...unwired, items: [upstream, { ...video, form: { prompt: "动起来", source_assets: [manual] } }] };
    opens(boardAt(3, server));
    apiMocks.updateBoard.mockResolvedValue(boardAt(4, stored));

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange(unwired));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700);
    });

    expect(canvasHarness.api.patch).toHaveBeenCalledWith("V", { form: { prompt: "动起来", source_assets: [manual] } });
  });

  it("自动保存还在路上时点生成:生成等它回来,带着它换来的新版本号,不和自己撞 409", async () => {
    const server: BoardCanvas = {
      items: [{ id: "img", kind: "image", x: 0, y: 0, width: 260, height: 180 }],
      edges: [],
      markers: [],
    };
    const moved: BoardCanvas = { ...server, items: [{ ...server.items[0], x: 40 }] };
    const save = deferred<Board>();
    opens(boardAt(3, server));
    apiMocks.updateBoard.mockReturnValue(save.promise);
    apiMocks.runOnBoard.mockResolvedValue(
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
      generating = props().onRun({ producer: "generate", item_id: "img", kind: "image", x: 0, y: 0, form: { prompt: "一只猫" } });
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(apiMocks.runOnBoard).not.toHaveBeenCalled();

    await act(async () => {
      save.resolve(boardAt(4, moved));
      await generating;
    });
    expect(apiMocks.runOnBoard).toHaveBeenCalledTimes(1);
    expect(apiMocks.runOnBoard.mock.calls[0][1]).toMatchObject({ base_revision: 4, item_id: "img" });
  });
});

/**
 * 一台**认版本号**的假服务端:保存、在画板上跑带的 base_revision 不是当前那一版就 409 —— 和后端 update_board /
 * ensure_revision 一样。`serverWrite` 是服务端自己写的一格(回执落下产出、别的格子的占位):版本号 +1。
 * 此前的桩不看版本号,「回执一落、下一次编辑就撞 409、本地被整份换掉」这件事测不出来。
 */
function strictServer(initial: BoardCanvas) {
  const state = { canvas: initial, revision: 3 };
  const conflict = () => new ApiError("revision conflict", 409, "{}");
  apiMocks.listBoards.mockImplementation(async () => [boardAt(state.revision, state.canvas)]);
  apiMocks.getBoard.mockImplementation(async () => boardAt(state.revision, state.canvas));
  apiMocks.updateBoard.mockImplementation(async (_id: string, body: { base_revision: number; canvas: BoardCanvas }) => {
    if (body.base_revision !== state.revision) throw conflict();
    state.canvas = body.canvas;
    state.revision += 1;
    return boardAt(state.revision, state.canvas);
  });
  return {
    state,
    conflict,
    serverWrite(change: (canvas: BoardCanvas) => BoardCanvas) {
      state.canvas = change(state.canvas);
      state.revision += 1;
    },
  };
}

describe("服务端那一版前进了(回执、占位、智能体),本地手上还有没存的改动", () => {
  const running = { id: "img", kind: "image" as const, x: 0, y: 0, width: 260, height: 180, run: { status: "running" as const, job_id: "job-1" } };
  const note = { id: "n1", kind: "note" as const, x: 400, y: 0, width: 220, height: 140, text: "一只猫" };

  it("产出刚落下时拖了一格:保存撞了版本号就合上最新那一版再存 —— 拖的位置和产出都在,不提示冲突", async () => {
    const server = strictServer({ items: [running, note], edges: [], markers: [] });
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());

    //: 回执落下(服务端写的,版本 +1),同一刻人把便签拖开了 —— 本地还不知道有新的一版。
    server.serverWrite((canvas) => ({ ...canvas, items: [{ ...running, asset_id: "a1", run: { status: "succeeded" } }, note] }));
    act(() => props().onChange({ items: [running, { ...note, x: 520 }], edges: [], markers: [] }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });

    expect(apiMocks.updateBoard.mock.calls.length, "撞了一次,合好之后又存了一次").toBe(2);
    const stored = new Map(server.state.canvas.items.map((one) => [one.id, one]));
    expect(stored.get("n1")?.x, "拖的位置存上了").toBe(520);
    expect(stored.get("img")).toMatchObject({ asset_id: "a1", run: { status: "succeeded" } });
    expect(adoptedItem("n1")?.x, "本地那份没被整份换掉").toBe(520);
    expect(adoptedItem("img")?.asset_id).toBe("a1");
    expect(toastMocks.error, "自己的生成落地不是冲突").not.toHaveBeenCalled();
  });

  it("有没存的改动时轮询到产出:照样采用那一版、改动合在上面,接着带新版本号存 —— 一次 409 都不撞", async () => {
    const server = strictServer({ items: [running, note], edges: [], markers: [] });
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    server.serverWrite((canvas) => ({ ...canvas, items: [{ ...running, asset_id: "a1", run: { status: "succeeded" } }, note] }));
    //: 画布桩照真的那样:采用了哪一份,之后的编辑就从那一份接着改。
    let local: BoardCanvas = { items: [running, note], edges: [], markers: [] };
    canvasHarness.api.adopt.mockImplementation((canvas: BoardCanvas) => {
      local = canvas;
    });
    //: 人一直在拖(每 0.5 秒一下),自动保存一直等不到,轮询先到。
    for (let step = 1; step <= 6; step += 1) {
      local = { ...local, items: local.items.map((one) => (one.id === "n1" ? { ...one, x: 400 + step * 10 } : one)) };
      const next = local;
      act(() => props().onChange(next));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });
    }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(canvasHarness.api.adopt).toHaveBeenCalled();
    expect(apiMocks.updateBoard.mock.results.every((one) => one.type === "return")).toBe(true);
    const stored = new Map(server.state.canvas.items.map((one) => [one.id, one]));
    expect(stored.get("n1")?.x).toBe(460);
    expect(stored.get("img")?.asset_id).toBe("a1");
  });

  it("刚敲的字、刚按的撤销还攒在画布的并步窗口里时轮询到产出:合在画布此刻那一份上,不被上一次汇出的那份冲掉", async () => {
    const server = strictServer({ items: [running, note], edges: [], markers: [] });
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    //: 画布此刻的样子(还没到 400ms,没汇给上层):便签上刚敲了字。上层手上那份还是打开时的。
    canvasHarness.api.flush.mockImplementation(() => ({ items: [running, { ...note, text: "刚敲的" }], edges: [], markers: [] }));
    server.serverWrite((canvas) => ({ ...canvas, items: [{ ...running, asset_id: "a1", run: { status: "succeeded" } }, note] }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2600);
    });

    expect(adoptedItem("n1")?.text, "刚敲的字留着").toBe("刚敲的");
    expect(adoptedItem("img")?.asset_id).toBe("a1");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(server.state.canvas.items.find((one) => one.id === "n1")?.text, "存回去的也是它").toBe("刚敲的");
  });

  it("智能体改板批准之后,打开着的画板合上那一版 —— 本地没存的改动照留,不等下一次保存撞版本号", async () => {
    const server = strictServer({ items: [note], edges: [], markers: [] });
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange({ items: [{ ...note, text: "我刚改的" }], edges: [], markers: [] }));
    //: 智能体加了一张便签(确认卡批准、服务端执行),确认卡那边照例作废缓存。
    server.serverWrite((canvas) => ({ ...canvas, items: [...canvas.items, { id: "agent", kind: "note", x: 0, y: 300, text: "智能体加的" }] }));
    await act(async () => {
      invalidateAfterDecision(queryClient, "w1");
      await vi.advanceTimersByTimeAsync(10);
    });

    expect(adopted()?.items.map((one) => one.id)).toEqual(["n1", "agent"]);
    expect(adoptedItem("n1")?.text, "本地没存的那句照留").toBe("我刚改的");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(apiMocks.updateBoard.mock.results.every((one) => one.type === "return"), "一次 409 都不撞").toBe(true);
    expect(server.state.canvas.items.map((one) => [one.id, one.text])).toEqual([["n1", "我刚改的"], ["agent", "智能体加的"]]);
  });

  it("点生成时别的格子的回执刚落下:合上最新那一版再发一次,不报「生成失败」", async () => {
    const slot = { id: "slot", kind: "image" as const, x: 0, y: 300, width: 260, height: 180, form: { producer: "generate" as const } };
    const server = strictServer({ items: [running, slot], edges: [], markers: [] });
    apiMocks.runOnBoard.mockImplementation(async (_id: string, body: { base_revision: number; item_id: string }) => {
      if (body.base_revision !== server.state.revision) throw server.conflict();
      server.serverWrite((canvas) => ({
        ...canvas,
        items: canvas.items.map((one) => (one.id === body.item_id ? { ...one, run: { status: "running", job_id: "job-2" } } : one)),
      }));
      return boardAt(server.state.revision, server.state.canvas);
    });
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    server.serverWrite((canvas) => ({ ...canvas, items: [{ ...running, asset_id: "a1", run: { status: "succeeded" } }, slot] }));

    await act(async () => {
      await props().onRun({ producer: "generate", item_id: "slot", kind: "image", x: 0, y: 300, form: { prompt: "一只猫" } });
    });

    expect(apiMocks.runOnBoard).toHaveBeenCalledTimes(2);
    expect(apiMocks.runOnBoard.mock.calls[1][1]).toMatchObject({ base_revision: 4, item_id: "slot" });
    expect(toastMocks.error).not.toHaveBeenCalled();
    expect(adoptedItem("slot")?.run).toEqual({ status: "running", job_id: "job-2" });
    expect(adoptedItem("img")?.asset_id).toBe("a1");
  });
});

describe("能力的产出落在视野外", () => {
  it("新落下的几格全看不见:说一声、带「去看看」,点了跳过去 —— 不自己把视野拽走", async () => {
    const note = { id: "n1", kind: "note" as const, x: 0, y: 0, width: 220, height: 140, text: "hello",
                   run: { status: "running" as const, job_id: "job-9", ability: "node:translate" as const } };
    const derived = { id: "n1-out-1", kind: "note" as const, x: 3000, y: 0, width: 220, height: 140, text: "HELLO" };
    opens(boardAt(3, { items: [note], edges: [], markers: [] }));
    apiMocks.getBoard.mockResolvedValue(boardAt(4, {
      items: [{ ...note, run: { status: "succeeded", ability: "node:translate" } }, derived],
      edges: [{ id: "n1->n1-out-1", source: "n1", target: "n1-out-1" }],
      markers: [],
    }));
    canvasHarness.api.isInView.mockReturnValue(false);
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(canvasHarness.api.isInView).toHaveBeenCalledWith({ x: 3000, y: 0, width: 220, height: 140 });
    const [text, options] = toastMocks.success.mock.calls.at(-1) as [string, { action: { label: string; onClick: () => void } }];
    expect(text).toBe("boardOutputsOffscreen");
    expect(options.action.label).toBe("boardShowOutputs");
    expect(canvasHarness.api.focusItem, "不自己把视野挪过去").not.toHaveBeenCalled();
    options.action.onClick();
    expect(canvasHarness.api.focusItem).toHaveBeenCalledWith("n1-out-1");
  });
});

describe("一格的能力(把它的内容变成新内容)", () => {
  const TOOL = {
    id: "node:translate", type: "translate", label: "翻译", description: "把文本翻译成目标语言:Google 免费接口或 AI 供应商。",
    category: "工作流面板的分组", config: {}, outputs: [], output_types: {}, output_labels: {}, plugin_name: "", tool_name: "", body_scope: {},
    hosts: ["note", "document"], role: "ability", host_fields: { note: "text", document: "text" },
    permission: "edit", effects: "none", fills_empty_slot: false,
    board_group: "text", board_group_label: "处理文字", board_description: "把便签或文档里的文字翻成另一种语言",
  };

  it("工具条「添加」里只有格子,按动词分组(新建 / 从库里放 / 整理);没有工具那一组", async () => {
    Object.assign(Element.prototype, { scrollIntoView: () => {}, hasPointerCapture: () => false, releasePointerCapture: () => {} });
    opens(boardAt(3, { items: [], edges: [], markers: [] }));
    apiMocks.listBoardProducers.mockResolvedValue([TOOL]);

    const view = mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    await vi.waitFor(() => expect((canvasHarness.props as { producers?: unknown[] }).producers).toEqual([TOOL]));
    act(() => {
      fireEvent.click(view.container.ownerDocument.querySelector<HTMLElement>("[data-board-add-item]")!);
    });
    await vi.waitFor(() => expect(document.querySelectorAll("[cmdk-item], [role=option]").length).toBeGreaterThan(0));
    const rows = [...document.querySelectorAll<HTMLElement>("[cmdk-item], [role=option]")];
    expect(rows.some((one) => one.textContent?.includes("翻译")), "工具不在「添加」里").toBe(false);
    for (const group of ["boardsGroupCreate", "boardsGroupFromLibrary", "boardsGroupOrganize"]) {
      expect(document.body.textContent).toContain(group);
    }
    expect(document.body.textContent).not.toContain("处理文字");
  });

  it("跑一项能力发的是宿主那一格 + 能力 + 设置;停止取消的是这一格这一轮的任务;跑完右边新建的几格随服务端那份落下来", async () => {
    const note = { id: "n1", kind: "note" as const, x: 0, y: 0, width: 220, height: 140, text: "hello", form: { producer: "write" as const } };
    const server: BoardCanvas = { items: [note], edges: [], markers: [] };
    const setting = { config: { target_lang: "en" }, bindings: {} };
    const running = {
      ...note,
      form: { abilities: { "node:translate": setting }, producer: "write" as const },
      run: { status: "running" as const, job_id: "job-9", ability: "node:translate" as const },
    };
    const derived = { id: "n1-out-1", kind: "note" as const, x: 360, y: 0, width: 220, height: 140, text: "HELLO", form: { producer: "write" as const } };
    const settled: BoardCanvas = {
      items: [{ ...running, run: { status: "succeeded", ability: "node:translate" } }, derived],
      edges: [{ id: "n1->n1-out-1", source: "n1", target: "n1-out-1" }],
      markers: [],
    };
    opens(boardAt(3, server));
    apiMocks.runOnBoard.mockResolvedValue(boardAt(4, { ...server, items: [running] }));
    apiMocks.getBoard.mockResolvedValue(boardAt(5, settled));
    apiMocks.cancelJob.mockResolvedValue({ id: "job-9" });

    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => props().onChange(server));
    await act(async () => {
      await props().onRun({ producer: "node:translate", item_id: "n1", kind: "note", x: 0, y: 0, form: { config: { target_lang: "en" }, bindings: {} } });
    });
    expect(apiMocks.runOnBoard.mock.calls[0][1]).toMatchObject({
      producer: "node:translate", item_id: "n1", kind: "note", form: { config: { target_lang: "en" }, bindings: {} },
    });
    //: 宿主那一格就地换上服务端的表单和运行态(能力的设置、这一轮是哪一项)。
    expect(adoptedItem("n1")).toMatchObject({ run: running.run, form: running.form });

    act(() => props().onChange({ ...server, items: [running] }));
    await act(async () => {
      await (canvasHarness.props as { onStop: (id: string) => Promise<void> }).onStop("n1");
    });
    expect(apiMocks.cancelJob).toHaveBeenCalledWith("job-9");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(adopted()).toEqual(settled);
  });

  it("能力跑不起来(比如没有这个插件的连接):提示说的是工具,不是「生成失败」", async () => {
    opens(boardAt(3, { items: [], edges: [], markers: [] }));
    apiMocks.runOnBoard.mockRejectedValue(new Error("你还没有能跑「去背景」的「抠图」连接"));
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    await act(async () => {
      await props().onRun({ producer: "node:plugin.cut.out", item_id: "i1", kind: "image", x: 0, y: 0, form: { config: {}, bindings: {} } });
    });
    expect(toastMocks.error).toHaveBeenCalledWith("boardToolFailed", { description: "你还没有能跑「去背景」的「抠图」连接" });
  });

  it("拖进来一批文件,中间一个传不上:传上的照样上画板、素材库照样刷新,最后说清几个没进来", async () => {
    opens(boardAt(3, { items: [], edges: [], markers: [] }));
    apiMocks.importAsset
      .mockResolvedValueOnce({ id: "a1", name: "一.png", kind: "image" })
      .mockRejectedValueOnce(new Error("格式不支持"))
      .mockResolvedValueOnce({ id: "a3", name: "三.mp4", kind: "video" });
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    const files = ["一.png", "二.heic", "三.mp4"].map((name) => new File(["x"], name));
    let placed: unknown;
    await act(async () => {
      placed = await (canvasHarness.props as { onDropFiles: (files: File[]) => Promise<unknown> }).onDropFiles(files);
    });
    expect(apiMocks.importAsset).toHaveBeenCalledTimes(3);
    expect(placed).toEqual([
      { id: "a1", name: "一.png", kind: "image" },
      { id: "a3", name: "三.mp4", kind: "video" },
    ]);
    expect(toastMocks.error).toHaveBeenCalledWith("mediaImportPartial");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["assets", "w1"] });
    invalidate.mockRestore();
  });

  it("「添加 → 素材」放下的一格和拖进来的写同样的字段:素材 + 它的名字", async () => {
    Object.assign(Element.prototype, { scrollIntoView: () => {}, hasPointerCapture: () => false, releasePointerCapture: () => {} });
    opens(boardAt(3, { items: [], edges: [], markers: [] }));
    const view = mount();
    await vi.waitFor(() => expect(canvasHarness.props).not.toBeNull());
    act(() => {
      fireEvent.click(view.container.ownerDocument.querySelector<HTMLElement>("[data-board-add-item]")!);
    });
    await vi.waitFor(() => expect(document.querySelector('[data-value="pick-media"], [role=option][data-value="pick-media"]')).not.toBeNull());
    act(() => {
      fireEvent.click(document.querySelector<HTMLElement>('[data-value="pick-media"]')!);
    });
    await vi.waitFor(() => expect(pickerHarness.props?.open).toBe(true));
    act(() => (pickerHarness.props!.onPick as (asset: unknown) => void)({ id: "a9", name: "海报.png", kind: "image" }));
    expect(canvasHarness.api.add).toHaveBeenCalledWith("image", { asset_id: "a9", text: "海报.png" });
  });
});
