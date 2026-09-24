/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

const apiMocks = vi.hoisted(() => ({
  listBoards: vi.fn(),
  deleteBoard: vi.fn(),
  duplicateBoard: vi.fn(),
  updateBoard: vi.fn(),
}));
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));
vi.mock("sonner", () => ({ toast: toastMocks }));

const zh = messages["zh-CN"];
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: MessageKey) => zh[key],
  usePreferences: () => ({ locale: "zh-CN", t: (key: MessageKey) => zh[key] }),
}));

import type { Board, Workspace } from "@/api/client";
import { BoardsView } from "@/features/boards/BoardsView";

const workspace = { id: "w1", name: "测试工作区" } as Workspace;

function board(id: string, name: string): Board {
  return {
    id,
    workspace_id: "w1",
    name,
    canvas: { items: [], edges: [] },
    revision: 3,
    created_at: "2026-09-20T00:00:00",
    updated_at: "2026-09-20T00:00:00",
  } as Board;
}

let boards: Board[] = [];

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BoardsView workspace={workspace} />
    </QueryClientProvider>,
  );
}

/** 卡片本体(打开 / 勾选)那颗按钮。平时名字就是画板名,选择模式下是「选择: 名字」。 */
const card = (name: string) =>
  screen.getByRole("button", { name: new RegExp(`^(${zh.mediaSelectMode}: )?${name}$`) });

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "#/boards";
  boards = [board("b1", "灵感"), board("b2", "分镜"), board("b3", "配色")];
  apiMocks.listBoards.mockReset().mockImplementation(async () => boards);
  apiMocks.deleteBoard.mockReset().mockImplementation(async (id: string) => {
    boards = boards.filter((one) => one.id !== id);
  });
  apiMocks.duplicateBoard.mockReset();
  apiMocks.updateBoard.mockReset();
  toastMocks.success.mockReset();
  toastMocks.error.mockReset();
});

describe("画板列表的批量选择", () => {
  it("进入选择模式后点卡片是勾选而不是打开;选中的画主色圈和勾选圈", async () => {
    mount();
    await screen.findByText("灵感");
    fireEvent.click(screen.getByRole("button", { name: zh.mediaSelectMode }));

    fireEvent.click(card("灵感"));
    fireEvent.click(card("配色"));

    expect(screen.getByText(zh.mediaSelectedCount.replace("{n}", "2"))).toBeInTheDocument();
    expect(card("灵感")).toHaveAttribute("aria-pressed", "true");
    expect(card("分镜")).toHaveAttribute("aria-pressed", "false");
    // 没有进详情页 —— 选择模式下点卡片不打开。
    expect(localStorage.getItem("mosael:selected:boards:w1")).toBeNull();
    // 选择模式下单卡的「⋯」收起来,右上角让给勾选圈。
    expect(screen.queryByRole("button", { name: `${zh.studioActions}: 灵感` })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: zh.mediaSelectAll }));
    expect(screen.getByText(zh.mediaSelectedCount.replace("{n}", "3"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: zh.cancel }));
    expect(screen.queryByText(zh.mediaSelectedCount.replace("{n}", "3"))).toBeNull();
    expect(screen.getByRole("button", { name: `${zh.studioActions}: 灵感` })).toBeInTheDocument();
  });

  it("批量删除先确认;部分失败时报出来,删不掉的那张留着勾选好重试", async () => {
    apiMocks.deleteBoard.mockImplementation(async (id: string) => {
      if (id === "b3") throw new Error("boom");
      boards = boards.filter((one) => one.id !== id);
    });
    mount();
    await screen.findByText("灵感");
    fireEvent.click(screen.getByRole("button", { name: zh.mediaSelectMode }));
    fireEvent.click(card("灵感"));
    fireEvent.click(card("配色"));

    fireEvent.click(screen.getByRole("button", { name: zh.delete }));
    expect(apiMocks.deleteBoard).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(zh.boardsDeleteManyTitle.replace("{n}", "2"))).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: zh.confirm }));

    await waitFor(() => expect(apiMocks.deleteBoard).toHaveBeenCalledTimes(2));
    expect(apiMocks.deleteBoard).toHaveBeenCalledWith("b1", "w1");
    expect(apiMocks.deleteBoard).toHaveBeenCalledWith("b3", "w1");
    await waitFor(() =>
      expect(toastMocks.error).toHaveBeenCalledWith(zh.bulkPartialFailed.replace("{ok}", "1").replace("{failed}", "1")),
    );
    await waitFor(() => expect(screen.queryByText("灵感")).toBeNull());
    expect(screen.getByText(zh.mediaSelectedCount.replace("{n}", "1"))).toBeInTheDocument();
    expect(card("配色")).toHaveAttribute("aria-pressed", "true");
  });
});

describe("画板卡片的右键菜单", () => {
  it("列出打开、重命名、创建副本、选择、删除", async () => {
    mount();
    fireEvent.contextMenu(await screen.findByText("分镜"), { clientX: 10, clientY: 10 });
    const items = screen.getAllByRole("menuitem").map((item) => item.textContent?.trim());
    expect(items).toEqual([zh.boardsOpen, zh.rename, zh.boardsDuplicate, zh.boardsSelect, zh.delete]);
  });

  it("创建副本:按当前语言拼好名字交给后端,完成后提示", async () => {
    apiMocks.duplicateBoard.mockImplementation(async (id: string, body: { name: string }) => {
      const made = board(`${id}-copy`, body.name);
      boards = [made, ...boards];
      return made;
    });
    mount();
    fireEvent.contextMenu(await screen.findByText("分镜"), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByRole("menuitem", { name: zh.boardsDuplicate }));

    const name = zh.boardsCopyName.replace("{name}", "分镜");
    await waitFor(() => expect(apiMocks.duplicateBoard).toHaveBeenCalledWith("b2", { workspace_id: "w1", name }));
    await waitFor(() => expect(toastMocks.success).toHaveBeenCalledWith(zh.boardsDuplicated.replace("{name}", name)));
    expect(await screen.findByText(name)).toBeInTheDocument();
  });

  it("重命名走 RenameDialog,带着列表里的 revision 去改", async () => {
    apiMocks.updateBoard.mockImplementation(async (id: string, body: { name: string }) => {
      boards = boards.map((one) => (one.id === id ? { ...one, name: body.name, revision: 4 } : one));
      return boards.find((one) => one.id === id);
    });
    mount();
    fireEvent.contextMenu(await screen.findByText("分镜"), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByRole("menuitem", { name: zh.rename }));

    const input = await screen.findByDisplayValue("分镜");
    fireEvent.change(input, { target: { value: "分镜二稿" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() =>
      expect(apiMocks.updateBoard).toHaveBeenCalledWith("b2", { workspace_id: "w1", base_revision: 3, name: "分镜二稿" }),
    );
    expect(await screen.findByText("分镜二稿")).toBeInTheDocument();
  });

  it("删除要先确认,确认后才发请求", async () => {
    mount();
    fireEvent.contextMenu(await screen.findByText("配色"), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByRole("menuitem", { name: zh.delete }));
    expect(apiMocks.deleteBoard).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: zh.confirm }));
    await waitFor(() => expect(apiMocks.deleteBoard).toHaveBeenCalledWith("b3", "w1"));
    await waitFor(() => expect(screen.queryByText("配色")).toBeNull());
  });

  it("右键「选择」直接进选择模式并勾上这一张", async () => {
    mount();
    fireEvent.contextMenu(await screen.findByText("分镜"), { clientX: 10, clientY: 10 });
    fireEvent.click(screen.getByRole("menuitem", { name: zh.boardsSelect }));

    expect(screen.getByText(zh.mediaSelectedCount.replace("{n}", "1"))).toBeInTheDocument();
    expect(card("分镜")).toHaveAttribute("aria-pressed", "true");
  });
});
