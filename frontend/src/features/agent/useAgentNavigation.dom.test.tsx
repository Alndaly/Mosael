/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetActivePlaces } from "@/features/agent/activePlace";
import { adoptAgentSession } from "@/features/agent/sessionSelection";

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  getAgentSession: vi.fn(),
  listAgentSessions: vi.fn(),
  pendingView: "" as string,
  pendingAt: null as string | null,
  isMine: true,
}));
vi.mock("@/api/client", () => ({
  api: mocks.api,
  getAgentSession: mocks.getAgentSession,
  listAgentSessions: mocks.listAgentSessions,
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  isNotFound: () => false,
}));

import { useAgentNavigation } from "./useAgentNavigation";

const STUDIO = { kind: "studio", id: "" } as const;

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
  mocks.getAgentSession.mockImplementation(async (id: string) => ({
    id, workspace_id: "w1", title: id, is_mine: mocks.isMine, home_kind: "studio", home_id: "", home_name: "", home_state: "ok",
    pending_view: mocks.pendingView, pending_view_at: mocks.pendingAt,
  }));
  mocks.api.mockImplementation(async (_path: string, init?: { method?: string }) => {
    if (init?.method === "DELETE") {
      deletes += 1;
      if (failFirstDelete && deletes === 1) throw new Error("offline");
      mocks.pendingView = "";
      return {};
    }
    return {};
  });
}

/** 后端记的朴素 UTC 时间(没有时区后缀),和 pending_view_at 一样。 */
const serverTime = (msAgo: number) => new Date(Date.now() - msAgo).toISOString().replace("Z", "");

describe("智能体要求的页面跳转", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    resetActivePlaces();
    mocks.api.mockReset();
    mocks.getAgentSession.mockReset();
    mocks.listAgentSessions.mockReset().mockResolvedValue([]);
    mocks.pendingView = "";
    mocks.pendingAt = serverTime(1000);
    mocks.isMine = true;
  });

  it("跳一次、消费一次", async () => {
    adoptAgentSession("w1", STUDIO, "s-other");
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

  it("30 秒以前要求的跳转不跟:清掉,不跳 —— 你回来看结果,不该被拽走", async () => {
    adoptAgentSession("w1", STUDIO, "s-other");
    mocks.pendingView = "publish";
    mocks.pendingAt = serverTime(40_000);
    serveSessions();
    const onNavigate = vi.fn();
    mount(onNavigate);

    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith("/api/agent/sessions/s-other/view", { method: "DELETE" }),
    );
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("DELETE 失败、同一个待跳转被重新读回来时,再消费一次", async () => {
    adoptAgentSession("w1", STUDIO, "s-first");
    mocks.pendingView = "publish";
    serveSessions(true);
    const onNavigate = vi.fn();
    mount(onNavigate);

    // 两次消费之间隔着「DELETE 失败 → 失效 → 重新读回」一整轮请求;整套并行跑时 1 秒的默认等待不够。
    await waitFor(() => expect(onNavigate).toHaveBeenCalledTimes(2), { timeout: 5000 });
    expect(mocks.api.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(2);
  });

  it("正看着同事共享来的对话:不跳、也不替主人清掉 —— 那是智能体带主人过去", async () => {
    mocks.isMine = false;
    adoptAgentSession("w1", STUDIO, "s-shared");
    mocks.pendingView = "publish";
    serveSessions();
    const onNavigate = vi.fn();
    mount(onNavigate);
    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith("s-shared"));
    expect(mocks.api).not.toHaveBeenCalled();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("这一处是草稿(还没有对话)时不轮询、不跳", async () => {
    serveSessions();
    const onNavigate = vi.fn();
    mount(onNavigate);
    await waitFor(() => expect(mocks.listAgentSessions).toHaveBeenCalled());
    expect(mocks.getAgentSession).not.toHaveBeenCalled();
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
