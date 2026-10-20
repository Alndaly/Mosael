/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

/**
 * 创意画板的导出 / 导入。
 *
 * 画布本身换成一个桩(同 BoardDetailSync):这里钉的是**界面入口怎么和文件 / 接口说话**,
 * 不是 React Flow 怎么画。
 */
const apiMocks = vi.hoisted(() => ({
  listBoards: vi.fn(),
  getBoard: vi.fn(),
  createBoard: vi.fn(),
  deleteBoard: vi.fn(),
  duplicateBoard: vi.fn(),
  updateBoard: vi.fn(),
  listBoardProducers: vi.fn(),
  listComments: vi.fn(),
  listMembers: vi.fn(),
  importAsset: vi.fn(),
  cancelJob: vi.fn(),
  runOnBoard: vi.fn(),
  api: vi.fn(),
}));
const download = vi.hoisted(() => ({ saveJsonToDisk: vi.fn() }));
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const canvasHarness = vi.hoisted(() => ({
  props: null as null | Record<string, unknown>,
  api: {
    add: vi.fn(),
    patch: vi.fn(),
    absorb: vi.fn(),
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
vi.mock("@/lib/download", () => download);
vi.mock("sonner", () => ({ toast: toastMocks }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: MessageKey) => zh[key],
  usePreferences: () => ({ locale: "zh-CN", t: (key: MessageKey) => zh[key] }),
}));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "u1" } }) }));
vi.mock("@/components/layout/pageTrail", () => ({ usePageTrail: () => undefined }));
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

import { type Board, type BoardCanvas, type BoardSummary, type Workspace } from "@/api/client";
import { BoardsView } from "@/features/boards/BoardsView";

const zh = messages["zh-CN"];
const workspace = { id: "w1", name: "测试工作区", role: "editor" } as Workspace;

const CANVAS: BoardCanvas = {
  items: [
    { id: "n1", kind: "note", x: 12, y: 34, width: 220, height: 140, text: "一只猫", color: "yellow" },
    { id: "i1", kind: "image", x: 300, y: 34, asset_id: "asset-1" },
  ],
  edges: [{ id: "e1", source: "n1", target: "i1" }],
  markers: [{ id: "m1", name: "开头", x: 0, y: 0 }],
};

function boardAt(revision = 3): Board {
  return {
    id: "b1",
    workspace_id: "w1",
    name: "灵感",
    canvas: CANVAS,
    revision,
    created_at: "2026-09-20T00:00:00",
    updated_at: "2026-09-20T00:00:00",
  };
}

function summaryOf(one: Board): BoardSummary {
  return {
    id: one.id,
    workspace_id: one.workspace_id,
    name: one.name,
    revision: one.revision,
    item_count: one.canvas.items.length,
    preview: one.canvas,
    created_at: one.created_at,
    updated_at: one.updated_at,
  } as BoardSummary;
}

let boards: BoardSummary[] = [];

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BoardsView workspace={workspace} />
    </QueryClientProvider>,
  );
}

const fileInput = () => document.querySelector('input[type="file"]') as HTMLInputElement;

/** 选文件 —— 走的是界面上那条 hidden input(和真人点「导入」后选文件同一条)。 */
const choose = (file: File) => fireEvent.change(fileInput(), { target: { files: [file] } });

const jsonFile = (data: unknown, name = "导入.mosael-board.json") =>
  new File([JSON.stringify(data)], name, { type: "application/json" });

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "#/boards";
  boards = [summaryOf(boardAt())];
  apiMocks.listBoards.mockReset().mockImplementation(async () => boards);
  apiMocks.getBoard.mockReset().mockImplementation(async () => boardAt());
  apiMocks.createBoard.mockReset();
  apiMocks.updateBoard.mockReset();
  apiMocks.deleteBoard.mockReset();
  apiMocks.duplicateBoard.mockReset();
  apiMocks.listBoardProducers.mockReset().mockResolvedValue([]);
  apiMocks.listComments.mockReset().mockResolvedValue([]);
  apiMocks.listMembers.mockReset().mockResolvedValue({ members: [] });
  apiMocks.importAsset.mockReset();
  apiMocks.cancelJob.mockReset();
  apiMocks.runOnBoard.mockReset();
  apiMocks.api.mockReset().mockResolvedValue([]);
  canvasHarness.props = null;
  Object.values(canvasHarness.api).forEach((one) => typeof one === "function" && (one as ReturnType<typeof vi.fn>).mockReset());
  canvasHarness.api.flush.mockReturnValue(CANVAS);
  canvasHarness.api.isInView.mockReturnValue(true);
  download.saveJsonToDisk.mockReset();
  toastMocks.success.mockReset();
  toastMocks.error.mockReset();
});

describe("导出当前画板", () => {
  it("从操作条导出:文件名、format / version / name / canvas 都对,且不再请求一次详情", async () => {
    localStorage.setItem("mosael:selected:boards:w1", "b1");
    mount();

    //: 导出是「更多」那颗菜单里的一项(维护者:画板级动作收在弹窗里,别在工具栏上再摆一颗图标)。
    fireEvent.click(await screen.findByRole("button", { name: zh.more }));
    fireEvent.click(await screen.findByRole("menuitem", { name: zh.boardsExport }));

    await waitFor(() => expect(download.saveJsonToDisk).toHaveBeenCalledTimes(1));
    const [filename, data] = download.saveJsonToDisk.mock.calls[0] as [string, Record<string, unknown>];
    expect(filename).toBe("灵感.mosael-board.json");
    expect(data).toEqual({ format: "mosael.board", version: 1, name: "灵感", canvas: CANVAS });
    //: 导出的是界面上这份 —— 没有为了导出再取一次画板。
    expect(apiMocks.getBoard).toHaveBeenCalledTimes(1);
  });
});

describe("导入画板文件", () => {
  it("合法文件 -> POST /boards 带上文件里的 canvas;重名加「副本」;列表里出现它", async () => {
    apiMocks.createBoard.mockImplementation(async (body: { workspace_id: string; name: string; canvas: BoardCanvas }) => {
      const made: Board = {
        id: "b9",
        workspace_id: body.workspace_id,
        name: body.name,
        canvas: body.canvas,
        revision: 1,
        created_at: "2026-09-21T00:00:00",
        updated_at: "2026-09-21T00:00:00",
      };
      boards = [summaryOf(made), ...boards];
      return made;
    });
    mount();
    await screen.findByText("灵感");

    choose(jsonFile({ format: "mosael.board", version: 1, name: "灵感", canvas: CANVAS }));

    await waitFor(() =>
      expect(apiMocks.createBoard).toHaveBeenCalledWith({
        workspace_id: "w1",
        name: "灵感 副本",
        canvas: CANVAS,
      }),
    );
    //: 新建一张,不改任何已有的画板。
    expect(apiMocks.updateBoard).not.toHaveBeenCalled();
    expect(apiMocks.listBoards).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("灵感 副本")).toBeInTheDocument();
    expect(toastMocks.success).toHaveBeenCalledWith(zh.boardsImported.replace("{name}", "灵感 副本"));
  });

  it("名字取文件里的 name,不是文件名", async () => {
    apiMocks.createBoard.mockImplementation(async (body: { name: string }) => ({
      ...boardAt(1),
      id: "b9",
      name: body.name,
      canvas: CANVAS,
    }));
    mount();
    await screen.findByText("灵感");

    choose(
      new File(
        [JSON.stringify({ format: "mosael.board", version: 1, name: "新画板", canvas: CANVAS })],
        "随便起的文件名.json",
        { type: "application/json" },
      ),
    );

    await waitFor(() =>
      expect(apiMocks.createBoard).toHaveBeenCalledWith({ workspace_id: "w1", name: "新画板", canvas: CANVAS }),
    );
  });

  it.each([
    {
      label: "不是 JSON",
      file: () => new File(["这不是 JSON"], "坏文件.json", { type: "application/json" }),
      expected: zh.boardsImportInvalidJson,
    },
    {
      label: "不是 mosael.board",
      file: () => jsonFile({ format: "something.else", version: 1, canvas: CANVAS }),
      expected: zh.boardsImportNotBoard,
    },
    {
      label: "没有 canvas",
      file: () => jsonFile({ format: "mosael.board", version: 1, name: "灵感" }),
      expected: zh.boardsImportNoCanvas,
    },
    {
      label: "版本不认识",
      file: () => jsonFile({ format: "mosael.board", version: 2, canvas: CANVAS }),
      expected: zh.boardsImportVersion.replace("{version}", "2"),
    },
    {
      label: "太大",
      file: () =>
        jsonFile({
          format: "mosael.board",
          version: 1,
          name: "太大",
          canvas: { items: [], edges: [], note: "x".repeat(2 * 1024 * 1024 + 1) },
        }),
      expected: zh.boardsImportTooLarge,
    },
  ])("坏文件「$label」-> 一句人话,不发创建请求", async ({ file, expected }) => {
    mount();
    await screen.findByText("灵感");

    choose(file());

    await waitFor(() => expect(toastMocks.error).toHaveBeenCalledWith(expected));
    expect(apiMocks.createBoard).not.toHaveBeenCalled();
  });
});
