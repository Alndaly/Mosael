/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const cards = [
  {
    id: "c1",
    tool: "run_host_code",
    summary: "⚠️ **不隔离**,直接在你的电脑上运行",
    permission: "write",
    requested_by: "mcp",
    session_id: null,
    payload: {},
    status: "pending",
  },
  {
    id: "c2",
    tool: "edit_timeline",
    summary: "改我自己那次对话里的时间线",
    permission: "write",
    requested_by: "agent",
    session_id: "s-mine",
    payload: {},
    status: "pending",
  },
];

//: 卡挂着的那段对话(卡上那一行「在…里开的」读它)。
const session = { id: "s-mine", workspace_id: "w1", title: "我的对话", is_mine: true, home_kind: "note", home_id: "n1", home_name: "周报", home_state: "ok" };
const api = vi.fn(async (path: string) => (path.startsWith("/api/agent/sessions/") ? session : [...cards]));

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: (path: string) => api(path),
}));

import { HEADER_STATUS_SLOT_ID } from "@/components/layout/headerSlot";
import { ConfirmationCenter } from "@/features/agent/ConfirmationCenter";
import { registerInlineConfirmSurface } from "@/features/agent/confirmSurface";

function renderCenter({ header = false }: { header?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      {/* 应用顶栏里留的那个位(AppShell 画它);收起来的胶囊住进去。 */}
      {header && <header data-testid="app-header"><div id={HEADER_STATUS_SLOT_ID} className="contents" /></header>}
      <ConfirmationCenter workspaceId="w1" />
    </QueryClientProvider>,
  );
}

afterEach(() => api.mockClear());

/**
 * 全局确认卡的摘要来自后端文案目录,写着「⚠️ **不隔离**,直接在你的电脑上运行一段 Python」——
 * 这是用户点「批准」之前唯一会读的一行,星号原样露着就把最要紧的那个词淹没了。
 */
it("摘要里的 **强调** 渲染成粗体", async () => {
  const { container } = renderCenter();
  expect((await screen.findByText("不隔离")).tagName).toBe("STRONG");
  expect(container.textContent).not.toContain("**");
});

/**
 * 中心的每张卡只有「批准 / 拒绝」。同事共享给我的对话里的卡我看得见、批不了(后端回 403),拉进来就是一张点不掉的卡 ——
 * 所以只向后端要我能拍板的那些;共享来的那种留在它自己的对话里,以只读的样子就地等主人。
 */
it("只拉我能拍板的卡", async () => {
  renderCenter();
  await screen.findByText("不隔离");
  const paths = api.mock.calls.map(([path]) => path).filter((path) => path.startsWith("/api/confirmations"));
  expect(paths.length).toBeGreaterThan(0);
  for (const path of paths) {
    const query = new URL(path, "http://x").searchParams;
    expect(query.get("status")).toBe("pending");
    expect(query.get("decidable")).toBe("true");
  }
});

it("聊天面板开着的那次对话,它的卡由面板管,中心让位", async () => {
  renderCenter();
  expect(await screen.findByText("改我自己那次对话里的时间线")).toBeTruthy();

  let unregister = () => {};
  act(() => {
    unregister = registerInlineConfirmSurface("s-mine");
  });
  await waitFor(() => expect(screen.queryByText("改我自己那次对话里的时间线")).toBeNull());
  // 没挂对话的卡(MCP 等外部智能体)照旧由中心兜底。
  expect(screen.getByText("不隔离")).toBeTruthy();

  act(() => unregister());
  expect(await screen.findByText("改我自己那次对话里的时间线")).toBeTruthy();
});

/**
 * 好几段对话同时在跑时,落到这里的卡要看得出是谁在问(ADR 0044 §9):卡上一行「在笔记《周报》里开的」和「回到那里」。
 */
it("挂在对话上的卡写着那段对话是在哪开的,点「回到那里」就去那一处接着它", async () => {
  const goHome = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ConfirmationCenter workspaceId="w1" goHome={goHome} />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("agentOpenedIn")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /agentGoHome/ }));
  expect(goHome).toHaveBeenCalledWith(session);
});

/**
 * 中心盖住页面右上角:笔记工具条的「AI 助手」、面板标题栏的「新对话 / 关闭」(智能体那一路 AGENT-10)。收起来是一颗写着
 * 几张在等的小胶囊;来了新卡自己再展开。挂在对话上的卡是自家智能体开的,不写「外部智能体请求」。
 */
it("收得起来:收成一颗写着几张在等的胶囊,点开回来;来了新卡自己展开", async () => {
  renderCenter();
  await screen.findByText("不隔离");
  fireEvent.click(screen.getByRole("button", { name: /confirmCenterTuck/ }));
  await waitFor(() => expect(screen.queryByText("不隔离")).toBeNull());
  expect(screen.getByRole("button", { name: /confirmCenterWaiting/ })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /confirmApprove/ })).toBeNull();

  cards.push({ id: "c3", tool: "edit_note", summary: "新来的一张", permission: "edit", requested_by: "agent", session_id: null, payload: {}, status: "pending" });
  try {
    expect(await screen.findByText("新来的一张", undefined, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByText("不隔离")).toBeTruthy();
  } finally {
    cards.pop();
  }

  fireEvent.click(screen.getByRole("button", { name: /confirmCenterTuck/ }));
  await waitFor(() => expect(screen.queryByText("不隔离")).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: /confirmCenterWaiting/ }));
  expect(await screen.findByText("不隔离")).toBeTruthy();
}, 15_000);

it("收起来的胶囊住在应用顶栏里,不浮在页面工具条上", async () => {
  renderCenter({ header: true });
  await screen.findByText("不隔离");
  fireEvent.click(screen.getByRole("button", { name: /confirmCenterTuck/ }));
  const pill = await screen.findByRole("button", { name: /confirmCenterWaiting/ });
  expect(screen.getByTestId("app-header").contains(pill)).toBe(true);
  fireEvent.click(pill);
  expect(await screen.findByText("不隔离")).toBeTruthy();
});

it("挂在对话上的卡写「智能体请求」,外部智能体的卡才写「外部智能体请求 · 谁」", async () => {
  renderCenter();
  await screen.findByText("改我自己那次对话里的时间线");
  expect(screen.getByText("confirmAgentRequest")).toBeTruthy();
  expect(screen.getByText("confirmTitle · mcp")).toBeTruthy();
  expect(screen.queryByText("confirmTitle · agent")).toBeNull();
});
