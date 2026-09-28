/** @vitest-environment jsdom */

/**
 * 「当前是哪个智能体会话」只有一个答案。
 *
 * 此前两个面板没有存储时回落到清单第一条却不告诉别人,浮标和页面跳转只读 localStorage ——
 * 于是对着浮标说话新建了一条会话,而不是对面板正显示的那条说;浮标写了新 id,已打开的面板也
 * 不跟着切。这里钉住:几个消费者看到的是同一条,任何一处换了,别处当场跟着换。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listAgentSessions: vi.fn(),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
}));
vi.mock("@/api/client", () => mocks);

import { agentSessionSelectionKey } from "@/features/agent/sessionSelection";
import { ensureAgentSession, useCurrentAgentSession, useUpdateAgentSession } from "./currentAgentSession";

const KEY = agentSessionSelectionKey("w1");
const session = (id: string) => ({ id, workspace_id: "w1", title: id }) as never;

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  //: 两个独立的消费者 —— 一个当面板,一个当浮标。
  const both = renderHook(
    () => ({ panel: useCurrentAgentSession("w1"), dock: useCurrentAgentSession("w1") }),
    { wrapper },
  );
  return { client, wrapper, both };
}

beforeEach(() => {
  window.localStorage.clear();
  mocks.listAgentSessions.mockReset().mockResolvedValue([session("s-a"), session("s-b")]);
  mocks.createAgentSession.mockReset();
  mocks.updateAgentSession.mockReset().mockResolvedValue({});
});

describe("当前智能体会话", () => {
  it("没选过时各处都回落到同一条,而且只是看着不写回", async () => {
    const { both } = setup();
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-a"));
    expect(both.result.current.dock.session?.id).toBe("s-a");
    //: 回落是现算的 —— 写回会把一次「看着」变成「选过」,清单旧的时候还会跨窗口来回抢。
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("一处选了别的,另一处当场跟着换(同一窗口,不轮询)", async () => {
    const { both } = setup();
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-a"));
    act(() => both.result.current.dock.select("s-b"));
    expect(both.result.current.panel.session?.id).toBe("s-b");
    expect(window.localStorage.getItem(KEY)).toBe("s-b");
  });

  it("别的窗口换了会话(storage 事件),这边也跟着换", async () => {
    const { both } = setup();
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-a"));
    act(() => {
      window.localStorage.setItem(KEY, "s-b");
      window.dispatchEvent(new StorageEvent("storage", { key: KEY }));
    });
    expect(both.result.current.panel.session?.id).toBe("s-b");
    expect(both.result.current.dock.session?.id).toBe("s-b");
  });

  it("别的窗口刚建的会话这边清单里还没有:重拉一次清单,然后显示它", async () => {
    const { both } = setup();
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-a"));
    mocks.listAgentSessions.mockResolvedValue([session("s-new"), session("s-a"), session("s-b")]);
    act(() => {
      window.localStorage.setItem(KEY, "s-new");
      window.dispatchEvent(new StorageEvent("storage", { key: KEY }));
    });
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-new"));
    //: 这边没有把「第一条」写回去,那个窗口的选择不会被抢走。
    expect(window.localStorage.getItem(KEY)).toBe("s-new");
  });

  it("用上回落的那条(发消息、说话、改设置)时,它才被记成选择", async () => {
    const { both, client } = setup();
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-a"));
    const used = await act(() => ensureAgentSession(client, "w1"));
    expect(used.id).toBe("s-a");
    expect(mocks.createAgentSession).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(KEY)).toBe("s-a");
  });

  it("一条都没有时建一条,各处都切到它;同时要两次也只建一条", async () => {
    mocks.listAgentSessions.mockResolvedValue([]);
    mocks.createAgentSession.mockResolvedValue(session("s-created"));
    const { both, client } = setup();
    await waitFor(() => expect(both.result.current.panel.listLoaded).toBe(true));
    expect(both.result.current.panel.session).toBeNull();

    const [first, second] = await act(() =>
      Promise.all([ensureAgentSession(client, "w1"), ensureAgentSession(client, "w1")]),
    );
    expect(first.id).toBe("s-created");
    expect(second.id).toBe("s-created");
    expect(mocks.createAgentSession).toHaveBeenCalledOnce();
    expect(both.result.current.panel.session?.id).toBe("s-created");
    expect(both.result.current.dock.session?.id).toBe("s-created");
  });

  it("删掉的是当前那条:放下选择,各处回落到剩下的第一条", async () => {
    window.localStorage.setItem(KEY, "s-a");
    const { both } = setup();
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-a"));
    act(() => both.result.current.panel.forget(["s-a"]));
    expect(both.result.current.panel.session?.id).toBe("s-b");
    expect(both.result.current.dock.session?.id).toBe("s-b");
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("还没有会话时改设置:先建出当前会话,再写进去", async () => {
    mocks.listAgentSessions.mockResolvedValue([]);
    mocks.createAgentSession.mockResolvedValue(session("s-created"));
    const { wrapper, both } = setup();
    await waitFor(() => expect(both.result.current.panel.listLoaded).toBe(true));
    const update = renderHook(() => useUpdateAgentSession("w1", null), { wrapper });

    await act(() => update.result.current.mutateAsync({ thinking_level: "high" }));
    expect(mocks.createAgentSession).toHaveBeenCalledWith({ workspace_id: "w1" });
    expect(mocks.updateAgentSession).toHaveBeenCalledWith("s-created", { thinking_level: "high" });
    expect(both.result.current.panel.session?.id).toBe("s-created");
  });
});
