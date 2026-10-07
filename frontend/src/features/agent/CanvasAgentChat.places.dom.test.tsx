/** @vitest-environment jsdom */

/**
 * 每一处各接各的对话(ADR 0044 §12 的 DOM 那一组)。断言的是**面板里画出来的那段对话**(消息正文)和**消息发进了哪段**
 * (发到哪个会话、带的 place)—— 不只看存储的键:标记落在空容器上,断言天然成立。
 *
 * 后端是内存里的一份假的:会话(带家)、消息、待跳转。页面就是一个登记了地方、挂着面板的组件;跳转由
 * useAgentNavigation 驱动,和 App 里一样。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

type Place = { kind: string; id: string };
type Session = {
  id: string; workspace_id: string; title: string; is_mine: boolean; status: string;
  home_kind: string; home_id: string; home_name: string; home_state: string;
  pending_view: string; pending_view_at: string | null;
};
type Message = { id: string; session_id: string; role: string; content: string; payload: Record<string, unknown>; error: null; created_at: string };

const backend = vi.hoisted(() => ({
  sessions: [] as Session[],
  messages: {} as Record<string, Message[]>,
  created: [] as unknown[],
  sent: [] as [string, Record<string, unknown>][],
  deletes: [] as string[],
  next: 1,
}));

function newSession(id: string, home: Place, title = id): Session {
  return {
    id, workspace_id: "w1", title, is_mine: true, status: "idle", home_kind: home.kind, home_id: home.id,
    home_name: "", home_state: "ok", pending_view: "", pending_view_at: null,
  };
}

function say(sessionId: string, content: string) {
  const list = (backend.messages[sessionId] ??= []);
  const message = { id: `m${backend.next++}`, session_id: sessionId, role: "user", content, payload: {}, error: null, created_at: "2026-10-07T00:00:00" };
  list.push(message);
  return message;
}

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  isNotFound: (error: unknown) => (error as { status?: number } | null)?.status === 404,
  listAgentSessions: vi.fn(async (_ws: string, home?: Place) =>
    backend.sessions.filter((one) => !home || (one.home_kind === home.kind && one.home_id === home.id)).map((one) => ({ ...one })),
  ),
  getAgentSession: vi.fn(async (id: string) => {
    const found = backend.sessions.find((one) => one.id === id);
    if (!found) throw Object.assign(new Error("gone"), { status: 404 });
    return { ...found };
  }),
  createAgentSession: vi.fn(async (body: { home: Place }) => {
    backend.created.push(body);
    const created = newSession(`s-new-${backend.next++}`, body.home, "新对话");
    backend.sessions.unshift(created);
    return { ...created };
  }),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  listAgentMessages: vi.fn(async (id: string) => [...(backend.messages[id] ?? [])]),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(async (id: string, body: { content: string }) => {
    backend.sent.push([id, body]);
    return say(id, body.content);
  }),
  api: vi.fn(async (path: string, init?: { method?: string }) => {
    if (init?.method === "DELETE") {
      const id = path.split("/")[4];
      backend.deletes.push(id);
      const found = backend.sessions.find((one) => one.id === id);
      if (found) Object.assign(found, { pending_view: "", pending_view_at: null });
    }
    return {};
  }),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear() {} }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_CONTEXT_CHARS: 4000,
  MAX_MESSAGE_CHARS: 8000,
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true, files: [], media: [], chips: [], uploading: false, previewModal: null,
    onPaste() {}, drop: { handlers: {}, overlay: null }, accept() {}, clear() {},
  }),
}));
vi.mock("@/features/agent/ChatComposer", () => ({
  ChatComposer: () => <textarea aria-label="composer" />,
  appendText: (doc: unknown) => doc,
  collectReferences: () => [],
  documentText: () => "你好",
  emptyDocument: { type: "doc", content: [] },
}));
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => null }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => null }));
vi.mock("@/features/agent/PendingDecisions", () => ({
  SessionDecisions: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PendingDecisions: () => null,
  JumpToLatestOrDecision: () => null,
}));
vi.mock("@/features/agent/QueuedMessages", () => ({ QueuedMessages: () => null }));

import { api, updateAgentSession } from "@/api/client";
import { CanvasAgentChat } from "./CanvasAgentChat";
import { resetActivePlaces, useAgentPlace } from "./activePlace";
import type { AgentPlace } from "./places";
import { adoptAgentSession, readChoice } from "./sessionSelection";
import { useAgentNavigation } from "./useAgentNavigation";

const PROJECT_A: AgentPlace = { kind: "project", id: "a" };
const NOTE_B: AgentPlace = { kind: "note", id: "b" };
const NOTE_C: AgentPlace = { kind: "note", id: "c" };
const STUDIO: AgentPlace = { kind: "studio", id: "" };

function Page({ place, testId = "panel" }: { place: AgentPlace; testId?: string }) {
  const registered = useAgentPlace(place);
  return (
    <div data-testid={testId}>
      <CanvasAgentChat
        contextLine=""
        emptyHint="empty-hint"
        placeholder="placeholder"
        rectKey={`test.${testId}`}
        workspaceId="w1"
        place={registered}
        mode="docked"
      />
    </div>
  );
}

/** 一个窗口:眼下这一页(没有就是素材页这种没有面板的页面)+ 智能体带你去。 */
let goTo: (place: AgentPlace | null) => void = () => {};
function Studio({ start }: { start: AgentPlace | null }) {
  const [page, setPage] = React.useState<AgentPlace | null>(start);
  goTo = setPage;
  useAgentNavigation({
    workspaceId: "w1",
    onNavigate: (view, id) => setPage(view === "notes" ? { kind: "note", id } : view === "editor" ? { kind: "project", id } : null),
  });
  return page ? <Page place={page} /> : null;
}

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const panel = (testId = "panel") => within(screen.getByTestId(testId));

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  window.sessionStorage.clear();
  resetActivePlaces();
  backend.sessions = [newSession("s1", PROJECT_A, "剪辑里的对话"), newSession("s9", { kind: "board", id: "x" }, "画板里的对话")];
  backend.messages = {};
  backend.created = [];
  backend.sent = [];
  backend.deletes = [];
  say("s1", "剪辑里说的话");
  say("s9", "画板里说的话");
  vi.mocked(updateAgentSession).mockClear();
  vi.mocked(api).mockClear();
});

it("换页不带对话:剪辑里聊着的那段,到了笔记里是空的;在笔记里发第一句,建的会话家在这篇笔记;回到剪辑还是那段", async () => {
  adoptAgentSession("w1", PROJECT_A, "s1");
  mount(<Studio start={PROJECT_A} />);
  expect(await panel().findByText("剪辑里说的话")).toBeTruthy();

  act(() => goTo(NOTE_B));
  expect(await panel().findByText("empty-hint")).toBeTruthy();
  expect(panel().queryByText("剪辑里说的话")).toBeNull();

  fireEvent.click(panel().getByRole("button", { name: "chatSend" }));
  await waitFor(() => expect(backend.sent).toHaveLength(1));
  expect(backend.created).toEqual([{ workspace_id: "w1", home: NOTE_B }]);
  const [target, body] = backend.sent[0];
  expect(target).toMatch(/^s-new-/);
  expect(body.place).toEqual(NOTE_B);
  expect(await panel().findByText("你好")).toBeTruthy();

  act(() => goTo(PROJECT_A));
  expect(await panel().findByText("剪辑里说的话")).toBeTruthy();
  expect(panel().queryByText("你好")).toBeNull();
});

it("智能体带着走:对话中途它带你去笔记 B,B 接着这段,下一句发进这段、带着 B;接着自己点开笔记 C,C 是空的", async () => {
  adoptAgentSession("w1", PROJECT_A, "s1");
  mount(<Studio start={PROJECT_A} />);
  expect(await panel().findByText("剪辑里说的话")).toBeTruthy();

  Object.assign(backend.sessions[0], { pending_view: "notes:b", pending_view_at: new Date().toISOString().replace("Z", "") });
  await waitFor(() => expect(backend.deletes).toContain("s1"), { timeout: 4000 });
  await waitFor(() => expect(readChoice("w1", NOTE_B)).toBe("s1"));
  expect(await panel().findByText("剪辑里说的话")).toBeTruthy();

  fireEvent.click(panel().getByRole("button", { name: "chatSend" }));
  await waitFor(() => expect(backend.sent).toHaveLength(1));
  expect(backend.sent[0][0]).toBe("s1");
  expect(backend.sent[0][1].place).toEqual(NOTE_B);
  expect(backend.created).toEqual([]);

  act(() => goTo(NOTE_C));
  expect(await panel().findByText("empty-hint")).toBeTruthy();
  expect(panel().queryByText("剪辑里说的话")).toBeNull();
  expect(readChoice("w1", NOTE_C)).toBe("");
});

it("带到没有面板的页面(素材页):AI Studio 那一处接住这段", async () => {
  adoptAgentSession("w1", PROJECT_A, "s1");
  mount(<Studio start={PROJECT_A} />);
  expect(await panel().findByText("剪辑里说的话")).toBeTruthy();

  Object.assign(backend.sessions[0], { pending_view: "media", pending_view_at: new Date().toISOString().replace("Z", "") });
  await waitFor(() => expect(screen.queryByTestId("panel")).toBeNull(), { timeout: 4000 });
  await waitFor(() => expect(readChoice("w1", STUDIO)).toBe("s1"), { timeout: 4000 });
});

it("40 秒前要求的跳转:不跳,清掉", async () => {
  adoptAgentSession("w1", PROJECT_A, "s1");
  mount(<Studio start={PROJECT_A} />);
  expect(await panel().findByText("剪辑里说的话")).toBeTruthy();

  Object.assign(backend.sessions[0], {
    pending_view: "notes:b", pending_view_at: new Date(Date.now() - 40_000).toISOString().replace("Z", ""),
  });
  await waitFor(() => expect(backend.deletes).toContain("s1"), { timeout: 4000 });
  expect(panel().getByText("剪辑里说的话")).toBeTruthy();
  expect(readChoice("w1", NOTE_B)).toBe("");
});

it("「其他对话」里挑一段:在这里接着它,它的家不变(一次 PATCH 都没有)", async () => {
  mount(<Page place={NOTE_B} />);
  expect(await panel().findByText("empty-hint")).toBeTruthy();

  fireEvent.click(panel().getByRole("button", { name: "wfAgentSessions" }));
  const elsewhere = await screen.findByRole("button", { name: "agentSessionsElsewhere" });
  fireEvent.click(elsewhere);
  fireEvent.click(await screen.findByRole("menuitemradio", { name: /画板里的对话/ }));

  expect(await panel().findByText("画板里说的话")).toBeTruthy();
  expect(readChoice("w1", NOTE_B)).toBe("s9");
  expect(updateAgentSession).not.toHaveBeenCalled();
  expect(backend.sessions.find((one) => one.id === "s9")).toMatchObject({ home_kind: "board", home_id: "x" });
  //: 家不在这里:标题下说一句它是在哪开的。
  expect(panel().getByText("agentThisWasOpenedIn")).toBeTruthy();
});

it("「新对话」只换这一处:两个面板同时开着,在 A 点,B 不动;什么都没建", async () => {
  backend.sessions.push(newSession("s2", NOTE_B, "笔记里的对话"));
  say("s2", "笔记里说的话");
  adoptAgentSession("w1", PROJECT_A, "s1");
  adoptAgentSession("w1", NOTE_B, "s2");
  mount(
    <>
      <Page place={PROJECT_A} testId="a" />
      <Page place={NOTE_B} testId="b" />
    </>,
  );
  expect(await panel("a").findByText("剪辑里说的话")).toBeTruthy();
  expect(await panel("b").findByText("笔记里说的话")).toBeTruthy();

  fireEvent.click(panel("a").getByRole("button", { name: "chatNewSession" }));
  expect(await panel("a").findByText("empty-hint")).toBeTruthy();
  expect(panel("a").queryByText("剪辑里说的话")).toBeNull();
  expect(panel("b").getByText("笔记里说的话")).toBeTruthy();
  expect(backend.created).toEqual([]);
});

it("工作台换标签页:面板换成那一张的对话,换回来还是原来那段", async () => {
  const saved: AgentPlace = { kind: "comfyui", id: "c1/人像.json" };
  const unsaved: AgentPlace = { kind: "comfyui", id: "c1#workflows/Unsaved Workflow.json" };
  backend.sessions.push(newSession("s-comfy", saved, "人像那张"));
  say("s-comfy", "人像那张里说的话");
  adoptAgentSession("w1", saved, "s-comfy");
  mount(<Studio start={saved} />);
  expect(await panel().findByText("人像那张里说的话")).toBeTruthy();

  act(() => goTo(unsaved));
  expect(await panel().findByText("empty-hint")).toBeTruthy();
  expect(panel().queryByText("人像那张里说的话")).toBeNull();

  act(() => goTo(saved));
  expect(await panel().findByText("人像那张里说的话")).toBeTruthy();
});
