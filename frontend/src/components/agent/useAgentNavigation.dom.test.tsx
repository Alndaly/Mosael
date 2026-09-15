/** @vitest-environment jsdom */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { agentSessionSelectionKey } from "@/features/ai-studio/sessionSelection";
import { useAgentNavigation, useSelectedAgentSessionId } from "./useAgentNavigation";

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  invalidate: vi.fn(),
  query: { data: undefined as { pending_view?: string } | undefined, dataUpdatedAt: 0 },
  queryOptions: undefined as { enabled?: boolean; queryKey?: unknown[] } | undefined,
}));

vi.mock("@/api/client", () => ({ api: mocks.api }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: mocks.invalidate }),
  useQuery: (options: { enabled?: boolean; queryKey?: unknown[] }) => {
    mocks.queryOptions = options;
    return mocks.query;
  },
}));

describe("agent navigation hooks", () => {
  beforeEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
    mocks.api.mockReset().mockResolvedValue({});
    mocks.invalidate.mockReset().mockResolvedValue(undefined);
    mocks.query.data = undefined;
    mocks.query.dataUpdatedAt = 0;
    mocks.queryOptions = undefined;
  });

  it("observes same-tab selection changes and removes its polling timer", () => {
    vi.useFakeTimers();
    const key = agentSessionSelectionKey("w1");
    window.localStorage.setItem(key, "session-1");
    const { result, unmount } = renderHook(() => useSelectedAgentSessionId("w1"));
    expect(result.current).toBe("session-1");

    window.localStorage.setItem(key, "session-2");
    act(() => vi.advanceTimersByTime(2000));
    expect(result.current).toBe("session-2");

    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("consumes one navigation once and keeps the shared query key", async () => {
    window.localStorage.setItem(agentSessionSelectionKey("w1"), "session-1");
    mocks.query.data = { pending_view: "editor:project-7" };
    mocks.query.dataUpdatedAt = 10;
    const onNavigate = vi.fn();
    const hook = renderHook(() => useAgentNavigation({ workspaceId: "w1", onNavigate }));

    await waitFor(() => expect(mocks.api).toHaveBeenCalledOnce());
    expect(onNavigate).toHaveBeenCalledWith("editor", "project-7");
    expect(mocks.api).toHaveBeenCalledWith("/api/agent/sessions/session-1/view", { method: "DELETE" });
    expect(mocks.queryOptions?.queryKey).toEqual(["agent-session", "session-1"]);

    hook.rerender();
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("retries consumption when DELETE failed and the same value was refetched", async () => {
    window.localStorage.setItem(agentSessionSelectionKey("w1"), "session-1");
    mocks.query.data = { pending_view: "publish" };
    mocks.query.dataUpdatedAt = 10;
    mocks.api.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({});
    const onNavigate = vi.fn();
    const hook = renderHook(() => useAgentNavigation({ workspaceId: "w1", onNavigate }));

    await waitFor(() => expect(mocks.invalidate).toHaveBeenCalledOnce());
    mocks.query.dataUpdatedAt = 11;
    hook.rerender();

    await waitFor(() => expect(mocks.api).toHaveBeenCalledTimes(2));
    expect(onNavigate).toHaveBeenCalledTimes(2);
  });

  it("does not poll or navigate before a session is selected", () => {
    const onNavigate = vi.fn();
    renderHook(() => useAgentNavigation({ workspaceId: "w1", onNavigate }));
    expect(mocks.queryOptions?.enabled).toBe(false);
    expect(onNavigate).not.toHaveBeenCalled();
    expect(mocks.api).not.toHaveBeenCalled();
  });
});

