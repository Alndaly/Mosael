/** @vitest-environment jsdom */

/**
 * 整理上下文的那几十秒,这段对话是占着的(智能体那一路 AGENT-5:和一轮同一个认领,压缩期间发的话进队列)。界面这时照
 * 「在跑」画 —— 状态行要说它在**整理**,不说「思考中」:那几十秒没有任何一轮在想事情,说思考会让人以为它在回答什么。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({ status: "idle" }));
const renders = vi.hoisted(() => ({ user: 0, assistant: 0 }));
const sent = vi.hoisted(() => [] as { content: string }[]);

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  isNotFound: () => false,
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", title: "t", is_mine: true, status: "idle", home_kind: "note", home_id: "a" }]),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", title: "t", is_mine: true, status: backend.status, home_kind: "note", home_id: "a" })),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  listAgentMessages: vi.fn(async () => [
    { id: "m1", session_id: "s1", role: "user", content: "第一句", payload: {}, error: null, created_at: "2026-10-08T00:00:00" },
    { id: "m2", session_id: "s1", role: "assistant", content: "第一句的回答", payload: { timeline: [{ type: "text", text: "第一句的回答" }] }, error: null, created_at: "2026-10-08T00:00:01" },
  ]),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(async (id: string, body: { content: string }) => {
    sent.push(body);
    return { id: "m3", session_id: id, role: "user", content: body.content, payload: {}, error: null, created_at: "2026-10-08T00:00:02" };
  }),
  api: vi.fn(async () => ({})),
  //: 整理要几十秒:这条测试里它一直没回来,后端那边这段对话是占着的(status=running)。
  compactAgentSession: vi.fn(() => {
    backend.status = "running";
    return new Promise(() => {});
  }),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/api/domains/sessions", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  streamAgentTurn: vi.fn(async () => new Response("data: {\"text\":\"\",\"done\":true,\"timeline\":[]}\n\n")),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
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
  ChatComposer: ({ value, onChange }: { value: { text?: string }; onChange: (doc: { type: string; text: string }) => void }) => (
    <textarea aria-label="composer" value={value.text ?? ""} onChange={(event) => onChange({ type: "doc", text: event.target.value })} />
  ),
  appendText: (doc: unknown) => doc,
  collectReferences: () => [],
  documentText: (doc: { text?: string }) => doc.text ?? "",
  emptyDocument: { type: "doc", text: "" },
}));
vi.mock("@/features/agent/userMessage", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  UserMessageContent: ({ content }: { content: string }) => {
    renders.user += 1;
    return <span>{content}</span>;
  },
}));
vi.mock("@/features/agent/ToolCalls", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  AgentTurnContent: ({ timeline }: { timeline?: { text?: string }[] }) => {
    renders.assistant += 1;
    return <span>{(timeline ?? []).map((item) => item.text).join("")}</span>;
  },
}));
vi.mock("@/features/agent/messageUsage", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  MessageUsageFooter: () => null,
}));
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => null }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({
  SessionSettingsMenu: ({ onCompact }: { onCompact?: () => void }) => (onCompact ? <button type="button" onClick={onCompact}>compact-now</button> : null),
}));
vi.mock("@/features/agent/PendingDecisions", () => ({
  SessionDecisions: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PendingDecisions: () => null,
  JumpToLatestOrDecision: () => null,
}));
vi.mock("@/features/agent/QueuedMessages", () => ({ QueuedMessages: () => null }));

import { CanvasAgentChat } from "./CanvasAgentChat";
import { adoptAgentSession } from "./sessionSelection";

const NOTE_A = { kind: "note", id: "a" } as const;

beforeEach(() => {
  window.sessionStorage.clear();
  adoptAgentSession("w1", NOTE_A, "s1");
  backend.status = "idle";
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

it("整理上下文期间状态行说「正在整理」,不说「思考中」", async () => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CanvasAgentChat contextLine="" emptyHint="hint" placeholder="p" rectKey="r" workspaceId="w1" place={NOTE_A} mode="docked" />
    </QueryClientProvider>,
  );
  await screen.findByText("第一句的回答");
  fireEvent.click(await screen.findByRole("button", { name: "compact-now" }));
  expect(await screen.findByText("agentCompactRunning", undefined, { timeout: 5000 })).toBeTruthy();
  expect(screen.queryByText("chatThinking")).toBeNull();
}, 15_000);
