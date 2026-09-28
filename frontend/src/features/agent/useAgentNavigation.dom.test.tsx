/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { agentSessionSelectionKey } from "@/features/agent/sessionSelection";

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  listAgentSessions: vi.fn(),
  pendingView: "" as string,
}));
vi.mock("@/api/client", () => ({
  api: mocks.api,
  listAgentSessions: mocks.listAgentSessions,
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
}));

import { useAgentNavigation } from "./useAgentNavigation";

const session = (id: string) => ({ id, workspace_id: "w1", title: id }) as never;

function mount(onNavigate: (view: string, id: string) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useAgentNavigation({ workspaceId: "w1", onNavigate }), { wrapper });
}

/** GET 会话详情回待跳转;DELETE 成功后就清掉(和后端一样)。 */
function serveSessions(failFirstDelete = false) {
  let deletes = 0;
  mocks.api.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (init?.method === "DELETE") {
      deletes += 1;
      if (failFirstDelete && deletes === 1) throw new Error("offline");
      mocks.pendingView = "";
      return {};
    }
    return { pending_view: mocks.pendingView, path };
  });
}

describe("智能体要求的页面跳转", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mocks.api.mockReset();
    mocks.listAgentSessions.mockReset().mockResolvedValue([session("s-first"), session("s-other")]);
    mocks.pendingView = "";
  });

  it("跳一次、消费一次", async () => {
    window.localStorage.setItem(agentSessionSelectionKey("w1"), "s-other");
    mocks.pendingView = "editor:project-7";
    serveSessions();
    const onNavigate = vi.fn();
    const hook = mount(onNavigate);

    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("editor", "project-7"));
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith("/api/agent/sessions/s-other/view", { method: "DELETE" }),
    );
    hook.rerender();
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("没选过会话时,跟着面板回落到的那一条走 —— 此前只读存储,这种跳转没人执行", async () => {
    mocks.pendingView = "publish";
    serveSessions();
    const onNavigate = vi.fn();
    mount(onNavigate);

    await waitFor(() => expect(onNavigate).toHaveBeenCalledWith("publish", ""));
    expect(mocks.api).toHaveBeenCalledWith("/api/agent/sessions/s-first");
  });

  it("DELETE 失败、同一个待跳转被重新读回来时,再消费一次", async () => {
    window.localStorage.setItem(agentSessionSelectionKey("w1"), "s-first");
    mocks.pendingView = "publish";
    serveSessions(true);
    const onNavigate = vi.fn();
    mount(onNavigate);

    // 两次消费之间隔着「DELETE 失败 → 失效 → 重新读回」一整轮请求;整套并行跑时 1 秒的默认等待不够。
    await waitFor(() => expect(onNavigate).toHaveBeenCalledTimes(2), { timeout: 5000 });
    expect(mocks.api.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(2);
  });

  it("一条会话都没有时不轮询、不跳", async () => {
    mocks.listAgentSessions.mockResolvedValue([]);
    const onNavigate = vi.fn();
    mount(onNavigate);
    await waitFor(() => expect(mocks.listAgentSessions).toHaveBeenCalled());
    expect(mocks.api).not.toHaveBeenCalled();
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
