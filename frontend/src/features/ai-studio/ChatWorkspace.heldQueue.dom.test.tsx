/** @vitest-environment jsdom */

/**
 * AI Studio 里按了停止,排着的话留在排队条里等人点「继续发送」(维护者 2026-10-09 拍板 D63)—— 和助手面板同一条。
 * 停下之后会话空闲:此前排队条只在跑着时读,扣下的那几条既不在条上、也不该在对话里。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { adoptAgentSession } from "@/features/agent/sessionSelection";

const backend = vi.hoisted(() => ({ held: true }));
const HELD = vi.hoisted(() => ({ id: "m2", session_id: "s1", role: "user", content: "排队的第二句", payload: { queued: true, held: true }, error: null, created_at: "2026-10-09T00:00:02" }));

vi.mock("@/api/client", () => ({
  isNotFound: () => false,
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  api: vi.fn(async () => ({})),
  agentManifest: vi.fn(async () => ({ version: "1" })),
  listAgentTools: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "停下的对话", is_mine: true }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "停下的对话", status: "idle", is_mine: true })),
  listAgentMessages: vi.fn(async () => [
    { id: "m1", session_id: "s1", role: "user", content: "第一句", payload: {}, error: null, created_at: "2026-10-09T00:00:00" },
    { id: "a1", session_id: "s1", role: "assistant", content: "说到一半", payload: { timeline: [{ type: "text", text: "说到一半" }] }, error: null, created_at: "2026-10-09T00:00:01" },
    ...(backend.held ? [HELD] : []),
  ]),
  listAgentQueue: vi.fn(async () => (backend.held ? [HELD] : [])),
  listAgentUsageEvents: vi.fn(async () => []),
  resumeQueuedMessage: vi.fn(async () => {
    backend.held = false;
    return { resumed: true };
  }),
  sendAgentMessage: vi.fn(),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/api/domains/sessions", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  streamAgentTurn: vi.fn(async () => new Response("data: {\"text\":\"\",\"done\":true,\"timeline\":[]}\n\n")),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear() {} }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_MESSAGE_CHARS: 8000,
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true, files: [], media: [], chips: [], uploading: false, previewModal: null,
    onPaste() {}, drop: { handlers: {}, overlay: null }, accept() {}, clear() {},
  }),
}));
//: 输入框换成一个受控的 textarea:打的字记成 `{ text }`;别处填进来的是真的段落文档,按段落拼回字。
vi.mock("@/features/agent/ChatComposer", () => {
  type Doc = { text?: string; content?: { content?: { text?: string }[] }[] };
  const documentText = (doc: Doc) => doc.text ?? (doc.content ?? []).map((p) => (p.content ?? []).map((n) => n.text ?? "").join("")).join("\n");
  return {
    ChatComposer: ({ value, onChange }: { value: Doc; onChange: (doc: { type: string; text: string }) => void }) => (
      <textarea aria-label="composer" value={documentText(value)} onChange={(event) => onChange({ type: "doc", text: event.target.value })} />
    ),
    appendText: (doc: unknown) => doc,
    collectReferences: () => [],
    documentText,
    emptyDocument: { type: "doc", text: "" },
  };
});
//: 气泡里最重的两样换成数次数的替身,其余照真的。
vi.mock("@/features/agent/userMessage", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  UserMessageContent: ({ content }: { content: string }) => {
    return <span>{content}</span>;
  },
}));
vi.mock("@/features/agent/ToolCalls", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  AgentTurnContent: ({ timeline }: { timeline?: { text?: string }[] }) => {
    return <span>{(timeline ?? []).map((item) => item.text).join("")}</span>;
  },
}));
vi.mock("@/features/agent/messageUsage", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  MessageUsageFooter: () => null,
  MessageFooter: () => null,
}));
vi.mock("@/features/ai-studio/SessionList", () => ({ SessionList: () => null }));
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => null }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => null }));
vi.mock("@/features/agent/effectiveModel", () => ({ useEffectiveChatModel: () => ({ model: "m" }) }));
vi.mock("@/features/agent/PendingDecisions", () => ({
  SessionDecisions: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PendingDecisions: () => null,
  JumpToLatestOrDecision: () => null,
}));
vi.mock("@/features/agent/trace/TraceView", () => ({ TraceView: () => null, TraceStatsBar: () => null }));
vi.mock("@/features/agent/trace/traceModel", () => ({ buildTurns: () => [] }));

import { resumeQueuedMessage } from "@/api/client";
import { ChatWorkspace } from "./ChatWorkspace";

beforeEach(() => {
  backend.held = true;
  window.localStorage.clear();
  window.sessionStorage.clear();
  adoptAgentSession("w1", { kind: "studio", id: "" }, "s1");
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

it("停下之后,扣下的那句在排队条上带「继续发送」、不在对话里;点了就放回去", async () => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ChatWorkspace workspace={{ id: "w1", name: "工作区" } as never} />
    </QueryClientProvider>,
  );
  await screen.findByText("说到一半");
  const resume = await screen.findByRole("button", { name: /chatQueuedResume/ });
  expect(screen.getAllByText("排队的第二句")).toHaveLength(1);

  fireEvent.click(resume);
  await waitFor(() => expect(vi.mocked(resumeQueuedMessage)).toHaveBeenCalledWith("s1", "m2"));
  await waitFor(() => expect(screen.queryByRole("button", { name: /chatQueuedResume/ })).toBeNull());
});
