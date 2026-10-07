/** @vitest-environment jsdom */

/**
 * 「这一处接着哪段对话」—— 每一处各有一个答案(ADR 0044 §3),打开时是一段还没建出来的草稿(维护者 2026-10-07 的修订)。
 *
 * 钉住:同一处的几个消费者(面板、浮标)看到同一段,任何一处换了别处当场跟着换;不同的地方各记各的,一处「新对话」不动
 * 别处;草稿不建会话,第一句话发出去才建、家是这一处;从别处挑一段是在这里接着聊,不改它的家(一次 PATCH 都没有)。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listAgentSessions: vi.fn(),
  getAgentSession: vi.fn(),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  isNotFound: (error: unknown) => (error as { status?: number } | null)?.status === 404,
}));
vi.mock("@/api/client", () => mocks);

import type { AgentPlace } from "@/features/agent/places";
import { adoptAgentSession, agentSessionSelectionKey } from "@/features/agent/sessionSelection";
import {
  ViewOnlySessionError,
  ensureAgentSession,
  startAgentDraft,
  useCurrentAgentSession,
  useSessionSettings,
  useUpdateAgentSession,
} from "./currentAgentSession";

const NOTE_A: AgentPlace = { kind: "note", id: "a" };
const NOTE_B: AgentPlace = { kind: "note", id: "b" };
type Home = { home_kind?: string; home_id?: string };
const session = (id: string, home: Home = { home_kind: "note", home_id: "a" }) =>
  ({ id, workspace_id: "w1", title: id, is_mine: true, home_name: "", home_state: "ok", ...home }) as never;
//: 同事共享来的:后端标 `is_mine: false`,只能看。
const shared = (id: string) => ({ ...(session(id) as object), is_mine: false }) as never;

const sessions: Record<string, unknown> = {};

function setup(place: AgentPlace = NOTE_A) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  //: 同一处的两个消费者 —— 一个当面板,一个当浮标。
  const both = renderHook(
    () => ({ panel: useCurrentAgentSession("w1", place), dock: useCurrentAgentSession("w1", place) }),
    { wrapper },
  );
  return { client, wrapper, both };
}

beforeEach(() => {
  window.sessionStorage.clear();
  for (const key of Object.keys(sessions)) delete sessions[key];
  for (const id of ["s-a", "s-b", "s-elsewhere"]) sessions[id] = session(id);
  sessions["s-elsewhere"] = session("s-elsewhere", { home_kind: "project", home_id: "p1" });
  mocks.listAgentSessions.mockReset().mockImplementation(async (_ws: string, home?: AgentPlace) =>
    home?.kind === "note" && home.id === "a" ? [sessions["s-a"], sessions["s-b"]] : [],
  );
  mocks.getAgentSession.mockReset().mockImplementation(async (id: string) => {
    if (!sessions[id]) throw Object.assign(new Error("gone"), { status: 404 });
    return sessions[id];
  });
  mocks.createAgentSession.mockReset();
  mocks.updateAgentSession.mockReset().mockResolvedValue({});
});

describe("每一处一个当前对话,打开时是草稿", () => {
  it("这里有对话也不自己接上:是一段草稿,而且什么都没写", async () => {
    const { both } = setup();
    await waitFor(() => expect(both.result.current.panel.listLoaded).toBe(true));
    expect(both.result.current.panel.here.map((one) => one.id)).toEqual(["s-a", "s-b"]);
    expect(both.result.current.panel.session).toBeNull();
    expect(both.result.current.panel.resolving).toBe(false);
    expect(window.sessionStorage.length).toBe(0);
    expect(mocks.createAgentSession).not.toHaveBeenCalled();
  });

  it("一处选了一段,同一处的另一个消费者当场跟着换;记在这个窗口(sessionStorage),不在 localStorage", async () => {
    const { both } = setup();
    act(() => both.result.current.dock.select("s-b"));
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-b"));
    expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", NOTE_A))).toBe("s-b");
    expect(window.localStorage.length).toBe(0);
  });

  it("各记各的:A 处选了一段,B 处还是草稿;A 处「新对话」不动 B 处", async () => {
    adoptAgentSession("w1", NOTE_B, "s-b");
    const a = setup(NOTE_A);
    const b = setup(NOTE_B);
    act(() => a.both.result.current.panel.select("s-a"));
    await waitFor(() => expect(a.both.result.current.panel.session?.id).toBe("s-a"));
    await waitFor(() => expect(b.both.result.current.panel.session?.id).toBe("s-b"));

    act(() => a.both.result.current.panel.startDraft());
    expect(a.both.result.current.panel.session).toBeNull();
    expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", NOTE_B))).toBe("s-b");
    expect(b.both.result.current.panel.session?.id).toBe("s-b");
    expect(mocks.createAgentSession).not.toHaveBeenCalled();
  });

  it("草稿上第一句话:在这一处建一段、家是这一处、只写这一处的键;同一处同时要两次也只建一段", async () => {
    mocks.createAgentSession.mockResolvedValue(session("s-created"));
    const { both, client } = setup();
    await waitFor(() => expect(both.result.current.panel.listLoaded).toBe(true));
    const [first, second] = await act(() =>
      Promise.all([ensureAgentSession(client, "w1", NOTE_A), ensureAgentSession(client, "w1", NOTE_A)]),
    );
    expect(first.id).toBe("s-created");
    expect(second.id).toBe("s-created");
    expect(mocks.createAgentSession).toHaveBeenCalledOnce();
    expect(mocks.createAgentSession).toHaveBeenCalledWith({ workspace_id: "w1", home: { kind: "note", id: "a" } });
    expect(both.result.current.panel.session?.id).toBe("s-created");
    expect(both.result.current.dock.session?.id).toBe("s-created");
    expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", NOTE_A))).toBe("s-created");
    expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", NOTE_B))).toBeNull();
  });

  it("不同的地方同时要:各建各的,家各是各的", async () => {
    mocks.createAgentSession.mockImplementation(async (body: { home: AgentPlace }) => session(`s-${body.home.id}`));
    const client = new QueryClient();
    const [a, b] = await Promise.all([ensureAgentSession(client, "w1", NOTE_A), ensureAgentSession(client, "w1", NOTE_B)]);
    expect([a.id, b.id]).toEqual(["s-a", "s-b"]);
    expect(mocks.createAgentSession).toHaveBeenCalledTimes(2);
  });

  it("用上选着的那段:不建、不改", async () => {
    adoptAgentSession("w1", NOTE_A, "s-b");
    const { client } = setup();
    const used = await act(() => ensureAgentSession(client, "w1", NOTE_A));
    expect(used.id).toBe("s-b");
    expect(mocks.createAgentSession).not.toHaveBeenCalled();
  });

  it("在这里接着别处开的那段:当前就是它,读它自己的详情,一次 PATCH 都没有(家不变)", async () => {
    const { both } = setup();
    await waitFor(() => expect(both.result.current.panel.listLoaded).toBe(true));
    act(() => both.result.current.panel.select("s-elsewhere"));
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-elsewhere"));
    expect(mocks.getAgentSession).toHaveBeenCalledWith("s-elsewhere");
    expect(mocks.updateAgentSession).not.toHaveBeenCalled();
    expect(both.result.current.panel.here.map((one) => one.id)).not.toContain("s-elsewhere");
  });

  it("选着的那段被删了(404):回到草稿,选择放下", async () => {
    adoptAgentSession("w1", NOTE_A, "s-deleted");
    const { both } = setup();
    await waitFor(() => expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", NOTE_A))).toBeNull());
    expect(both.result.current.panel.session).toBeNull();
  });

  it("删掉一段:指着它的每一处都回到草稿", async () => {
    adoptAgentSession("w1", NOTE_A, "s-a");
    adoptAgentSession("w1", NOTE_B, "s-a");
    adoptAgentSession("w1", { kind: "studio", id: "" }, "s-b");
    const { both } = setup();
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-a"));
    act(() => both.result.current.panel.forget(["s-a"]));
    expect(both.result.current.panel.session).toBeNull();
    expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", NOTE_B))).toBeNull();
    expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", { kind: "studio", id: "" }))).toBe("s-b");
  });

  it("「交给智能体」那种:startAgentDraft 只换成草稿,不建", () => {
    adoptAgentSession("w1", NOTE_A, "s-a");
    startAgentDraft("w1", NOTE_A);
    expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", NOTE_A))).toBeNull();
    expect(mocks.createAgentSession).not.toHaveBeenCalled();
  });
});

describe("草稿上的会话设置", () => {
  it("草稿上改设置不建会话;第一句话发出去时一起带上,之后草稿从默认开始", async () => {
    mocks.createAgentSession.mockResolvedValue(session("s-created"));
    const { wrapper, client } = setup();
    const settings = renderHook(() => useSessionSettings("w1", NOTE_A, null), { wrapper });
    await act(() => settings.result.current.update.mutateAsync({ thinking_level: "high", model: "m1", provider_profile_id: "p1" }));
    expect(mocks.createAgentSession).not.toHaveBeenCalled();
    expect(mocks.updateAgentSession).not.toHaveBeenCalled();
    expect(settings.result.current.settings).toMatchObject({ thinking_level: "high", model: "m1" });

    await act(() => ensureAgentSession(client, "w1", NOTE_A));
    expect(mocks.createAgentSession).toHaveBeenCalledWith({
      workspace_id: "w1", home: { kind: "note", id: "a" }, thinking_level: "high", model: "m1", provider_profile_id: "p1",
    });
    expect(settings.result.current.settings).toEqual({});
  });

  it("有会话时改设置直接写进去", async () => {
    const { wrapper } = setup();
    const update = renderHook(() => useUpdateAgentSession("w1", NOTE_A, session("s-a")), { wrapper });
    await act(() => update.result.current.mutateAsync({ thinking_level: "high" }));
    expect(mocks.updateAgentSession).toHaveBeenCalledWith("s-a", { thinking_level: "high" });
  });
});

describe("同事共享来的对话只能看", () => {
  it("点开它就看它,但发消息被拒,而且不悄悄另建一段", async () => {
    sessions["s-shared"] = shared("s-shared");
    adoptAgentSession("w1", NOTE_A, "s-shared");
    const { both, client } = setup();
    await waitFor(() => expect(both.result.current.panel.session?.id).toBe("s-shared"));
    expect(both.result.current.panel.readOnly).toBe(true);
    expect(both.result.current.dock.readOnly).toBe(true);

    await expect(act(() => ensureAgentSession(client, "w1", NOTE_A))).rejects.toBeInstanceOf(ViewOnlySessionError);
    expect(mocks.createAgentSession).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(agentSessionSelectionKey("w1", NOTE_A))).toBe("s-shared");
  });

  it("会话设置也不往里写", async () => {
    const { wrapper } = setup();
    const update = renderHook(() => useUpdateAgentSession("w1", NOTE_A, shared("s-shared")), { wrapper });
    await expect(act(() => update.result.current.mutateAsync({ thinking_level: "high" }))).rejects.toBeInstanceOf(
      ViewOnlySessionError,
    );
    expect(mocks.updateAgentSession).not.toHaveBeenCalled();
    expect(mocks.createAgentSession).not.toHaveBeenCalled();
  });
});
