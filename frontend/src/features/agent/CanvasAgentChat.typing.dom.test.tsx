/** @vitest-environment jsdom */

/**
 * 助手面板里打字不重画已有的消息(前端架构分析 FA-04,和 AI Studio 那份同一条)。
 *
 * 草稿此前是面板顶层的 state:每敲一个字整个面板重渲,对话越长打字越卡。现在草稿放在面板的渲染状态之外
 * (composerDraft),只有输入框和发送键订阅它。这里数消息里最重的两样东西各画了几次。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const renders = vi.hoisted(() => ({ user: 0, assistant: 0 }));
const sent = vi.hoisted(() => [] as { content: string }[]);

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  isNotFound: () => false,
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", title: "t", is_mine: true, status: "idle", home_kind: "note", home_id: "a" }]),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", title: "t", is_mine: true, status: "idle", home_kind: "note", home_id: "a" })),
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
  compactAgentSession: vi.fn(),
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
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => null }));
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
  renders.user = 0;
  renders.assistant = 0;
  sent.length = 0;
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

const box = () => screen.getByLabelText("composer") as HTMLTextAreaElement;

it("打字不重画已有的消息;发送键跟着框里空不空走,发出去的是打的那句,发完清空", async () => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CanvasAgentChat contextLine="" emptyHint="hint" placeholder="p" rectKey="r" workspaceId="w1" place={NOTE_A} mode="docked" />
    </QueryClientProvider>,
  );
  await screen.findByText("第一句");
  await screen.findByText("第一句的回答");
  const settled = { ...renders };
  expect(screen.getByRole("button", { name: "chatSend" })).toBeDisabled();

  for (const text of ["把", "把这", "把这段", "把这段改短"]) {
    fireEvent.change(box(), { target: { value: text } });
  }
  expect(box().value).toBe("把这段改短");
  expect(renders.user - settled.user, "打字时用户消息被重画了").toBe(0);
  expect(renders.assistant - settled.assistant, "打字时助手消息被重画了").toBe(0);
  expect(screen.getByRole("button", { name: "chatSend" })).toBeEnabled();

  fireEvent.click(screen.getByRole("button", { name: "chatSend" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0].content).toBe("把这段改短");
  await waitFor(() => expect(box().value).toBe(""));
});
