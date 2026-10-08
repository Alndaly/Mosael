/** @vitest-environment jsdom */

/**
 * 按了停止,排着的话留在排队条里等人点「继续发送」(维护者 2026-10-09 拍板 D63)。
 *
 * 此前排队条只在一轮跑着时才去读(`enabled: running`),停下之后会话空闲,条就没了;而那几条还带着 queued,对话里也不画
 * (或者画成已经发出去的样子)。现在空闲时照样读:扣下的那几条在条上,带「继续发送」,不在对话里。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  held: true,
  resumed: [] as string[],
}));

const HELD = { id: "m2", session_id: "s1", role: "user", content: "排队的第二句", payload: { queued: true, held: true }, error: null, created_at: "2026-10-09T00:00:02" };

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  isNotFound: () => false,
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", title: "t", is_mine: true, status: "idle", home_kind: "note", home_id: "a" }]),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", title: "t", is_mine: true, status: "idle", home_kind: "note", home_id: "a", updated_at: "2026-10-09T00:00:03" })),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  listAgentMessages: vi.fn(async () => [
    { id: "m1", session_id: "s1", role: "user", content: "第一句", payload: {}, error: null, created_at: "2026-10-09T00:00:00" },
    { id: "a1", session_id: "s1", role: "assistant", content: "说到一半", payload: { timeline: [{ type: "text", text: "说到一半" }] }, error: null, created_at: "2026-10-09T00:00:01" },
    ...(backend.held ? [HELD] : []),
  ]),
  listAgentQueue: vi.fn(async () => (backend.held ? [HELD] : [])),
  listAgentUsageEvents: vi.fn(async () => []),
  resumeQueuedMessage: vi.fn(async (_sid: string, id: string) => {
    backend.resumed.push(id);
    backend.held = false;
    return { resumed: true };
  }),
  sendAgentMessage: vi.fn(),
  api: vi.fn(async () => ({})),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear() {}, selected: [], restore() {} }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_CONTEXT_CHARS: 4000,
  MAX_MESSAGE_CHARS: 8000,
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true, files: [], media: [], chips: [], uploading: false, previewModal: null,
    onPaste() {}, drop: { handlers: {}, overlay: null }, accept() {}, clear() {}, restore() {},
  }),
}));
vi.mock("@/features/agent/ChatComposer", () => ({
  ChatComposer: () => <textarea aria-label="composer" />,
  appendText: (doc: unknown) => doc,
  collectReferences: () => [],
  documentText: () => "",
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

import { resumeQueuedMessage } from "@/api/client";
import { CanvasAgentChat } from "./CanvasAgentChat";
import { adoptAgentSession } from "./sessionSelection";

const NOTE_A = { kind: "note", id: "a" } as const;

beforeEach(() => {
  backend.held = true;
  backend.resumed = [];
  window.sessionStorage.clear();
  adoptAgentSession("w1", NOTE_A, "s1");
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

it("停下之后(会话空闲),扣下的那句在排队条上带「继续发送」,不在对话里;点了就放回去", async () => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CanvasAgentChat contextLine="" emptyHint="hint" placeholder="p" rectKey="r" workspaceId="w1" place={NOTE_A} mode="docked" />
    </QueryClientProvider>,
  );
  await screen.findByText("说到一半");
  const resume = await screen.findByRole("button", { name: /chatQueuedResume/ });
  //: 排队条上一份,对话里没有第二份(它还没发出去)。
  expect(screen.getAllByText("排队的第二句")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: /chatSteerAction/ })).toBeNull();

  fireEvent.click(resume);
  await waitFor(() => expect(vi.mocked(resumeQueuedMessage)).toHaveBeenCalledWith("s1", "m2"));
  await waitFor(() => expect(screen.queryByRole("button", { name: /chatQueuedResume/ })).toBeNull());
});
