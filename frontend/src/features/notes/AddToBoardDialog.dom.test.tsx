/** @vitest-environment jsdom */
/**
 * 「加到画板」的画板选择器:最近用过的排前面、能搜、能新建;挑了就把选中的字作为一张便签追加上去(服务端摆空位),
 * 记着来自哪篇笔记;加完一条提示,带「打开画板」。
 */
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { BOARD_ITEM_EVENT } from "@/lib/deepLink";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
const api = vi.hoisted(() => ({
  listBoards: vi.fn(),
  createBoard: vi.fn(),
  appendBoardNote: vi.fn(),
}));
vi.mock("@/api/domains/boards", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/boards")>()),
  ...api,
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast }));

const { AddToBoardDialog } = await import("./AddToBoardDialog");

const summary = (id: string, name: string, updated_at: string) =>
  ({ id, workspace_id: "ws", name, revision: 1, created_at: updated_at, updated_at, item_count: 0, preview: { items: [], edges: [] } });
const source = { kind: "note" as const, id: "n1", label: "宣传片周报", quote: "", revision: 3 };

beforeEach(() => {
  api.listBoards.mockResolvedValue([
    summary("b-old", "旧分镜", "2026-09-01T00:00:00"),
    summary("b-new", "新分镜", "2026-10-01T00:00:00"),
    summary("b-mid", "中间那张", "2026-09-15T00:00:00"),
  ]);
  api.appendBoardNote.mockImplementation(async (boardId: string) => ({ board_id: boardId, item_id: "note_9", revision: 2 }));
  api.createBoard.mockImplementation(async (body: { name?: string }) => ({ id: "b-created", name: body.name ?? "画板" }));
});
afterEach(() => { cleanup(); localStorage.clear(); vi.clearAllMocks(); });

function mount(onClose = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AddToBoardDialog workspaceId="ws" text="周二把脚本写完" source={source} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}
const rows = () => within(screen.getByRole("list")).getAllByRole("button").map((one) => one.getAttribute("data-board-row"));

it("最近改过的排前面;上次加过的那张排最前", async () => {
  localStorage.setItem("mosael.notes.lastBoard.ws", "b-old");
  mount();
  await waitFor(() => expect(rows()).toEqual(["b-old", "b-new", "b-mid"]));
});

it("能搜:按名字筛", async () => {
  mount();
  await waitFor(() => expect(rows()).toHaveLength(3));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "中间" } });
  expect(rows()).toEqual(["b-mid"]);
});

it("挑一张:追加便签(带来源),记住这张,提示带「打开画板」—— 点了打开那张板并定位到那一格", async () => {
  const onClose = mount();
  await waitFor(() => expect(rows()).toHaveLength(3));
  fireEvent.click(screen.getByRole("button", { name: /新分镜/ }));

  await waitFor(() => expect(api.appendBoardNote).toHaveBeenCalledWith("b-new", {
    workspace_id: "ws", text: "周二把脚本写完", source_note: { note_id: "n1", revision: 3, title: "宣传片周报" },
  }));
  await waitFor(() => expect(onClose).toHaveBeenCalled());
  expect(localStorage.getItem("mosael.notes.lastBoard.ws")).toBe("b-new");

  const [message, options] = toast.success.mock.calls[0] as [string, { action: { label: string; onClick: () => void } }];
  expect(message).toContain("新分镜");
  expect(options.action.label).toBe("打开画板");
  const focused: string[] = [];
  const listener = (event: Event) => focused.push(String((event as CustomEvent).detail));
  window.addEventListener(BOARD_ITEM_EVENT, listener);
  options.action.onClick();
  window.removeEventListener(BOARD_ITEM_EVENT, listener);
  expect(window.location.hash).toContain("board=b-new");
  expect(focused.map((raw) => JSON.parse(raw))).toEqual([{ boardId: "b-new", itemId: "note_9" }]);
});

it("新建画板:用搜索框里的字当名字,建好就加进去", async () => {
  mount();
  await waitFor(() => expect(rows()).toHaveLength(3));
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "开场构思" } });
  fireEvent.click(screen.getByRole("button", { name: /新建画板/ }));
  await waitFor(() => expect(api.createBoard).toHaveBeenCalledWith({ workspace_id: "ws", name: "开场构思" }));
  await waitFor(() => expect(api.appendBoardNote).toHaveBeenCalledWith("b-created", expect.objectContaining({ text: "周二把脚本写完" })));
});
