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
const api = vi.fn(async (path: string) => (path.startsWith("/api/agent/sessions/") ? session : cards));

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: (path: string) => api(path),
}));

import { ConfirmationCenter } from "@/features/agent/ConfirmationCenter";
import { registerInlineConfirmSurface } from "@/features/agent/confirmSurface";

function renderCenter() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
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
