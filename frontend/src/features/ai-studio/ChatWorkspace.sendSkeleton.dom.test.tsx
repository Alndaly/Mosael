/** @vitest-environment jsdom */

/**
 * 新建会话发送的那一小窗,不该把整列画面顶成骨架(用户实测:发送触发 Skeleton)。
 *
 * 机制:草稿发送 → ensure() 建出真实会话 → 消息查询切到新会话 id、数据还没回来,而会话详情
 * 要先经历一瞬「建好了、还没开跑」(status 不是 running)——两个条件叠上,加载骨架就盖住了
 * 整个对话区。第一条消息一到(或发送失败)就归位。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/** 新会话的第一批消息:先挂住(发送后那一小窗),测试后半段再放行。 */
const gate = vi.hoisted(() => {
  let release: (messages: unknown[]) => void = () => {};
  const pending = new Promise<unknown[]>((resolve) => {
    release = resolve;
  });
  return { pending, release: (messages: unknown[]) => release(messages) };
});

vi.mock("@/api/client", () => ({
  isNotFound: () => false,
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  api: vi.fn(async () => ({})),
  agentManifest: vi.fn(async () => ({ version: "1" })),
  listAgentTools: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => []),
  createAgentSession: vi.fn(async () => ({ id: "s-new", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "新对话", status: "idle", is_mine: true })),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s-new", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "新对话", status: "idle", is_mine: true })),
  listAgentMessages: vi.fn(async (id: string) => (id === "s-new" ? gate.pending : [])),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  getAgentVoice: vi.fn(async () => ({ speak_early: true })),
  sendAgentMessage: vi.fn(async () => ({ id: "m1", session_id: "s-new", role: "user", content: "第一句", payload: {}, error: null, created_at: "2026-10-21T00:00:00" })),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
  resumeQueuedMessage: vi.fn(),
}));
vi.mock("@/api/domains/sessions", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  streamAgentTurn: vi.fn(async () => new Response('data: {"text":"","done":true,"timeline":[]}\n\n')),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_MESSAGE_CHARS: 8000,
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true, files: [], media: [], chips: [], uploading: false, previewModal: null,
    onPaste() {}, drop: { handlers: {}, overlay: null }, accept() {}, clear() {},
  }),
}));
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
vi.mock("@/features/agent/userMessage", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  UserMessageContent: ({ content }: { content: string }) => <span>{content}</span>,
}));
vi.mock("@/features/agent/ToolCalls", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  AgentTurnContent: () => null,
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

import { sendAgentMessage } from "@/api/client";
vi.mock("@/components/jobs/SessionJobsCard", async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), SessionJobsCard: () => null }));

import { ChatWorkspace } from "./ChatWorkspace";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

it("草稿发送后、新会话的消息还没读到:不摆骨架;消息到了原地换上", async () => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ChatWorkspace workspace={{ id: "w1", name: "工作区" } as never} />
    </QueryClientProvider>,
  );

  fireEvent.change(await screen.findByLabelText("composer"), { target: { value: "第一句" } });
  fireEvent.submit(document.querySelector("form")!);
  await waitFor(() => expect(vi.mocked(sendAgentMessage)).toHaveBeenCalled());

  // 发送窗口:新会话的消息还挂着,骨架(给读屏的那句 + 假气泡)一个都不该出现。
  expect(screen.queryByText("chatLoadingSession")).toBeNull();
  expect(document.querySelector("[data-chat-transcript-skeleton]") ?? document.querySelector(".animate-pulse")).toBeNull();

  // 放行:第一批消息到了,发送的那句原地换上。
  gate.release([
    { id: "m1", session_id: "s-new", role: "user", content: "第一句", payload: {}, error: null, created_at: "2026-10-21T00:00:00" },
  ]);
  await screen.findByText("第一句");
});
