/** @vitest-environment jsdom */

/**
 * AI 工作台的对话和画布助手是同一套确认卡:卡摆在发起它的那次工具调用里,决定之后收成那一行的状态。
 * 两个入口各渲染各的消息列表(这边走 ChatBubble),所以各钉一条 —— 只在一边接上 provider 的话,
 * 另一边的卡会悄悄退回列表末尾(那正是这次要改掉的样子),而什么都不会报错。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { agentSessionSelectionKey } from "@/features/agent/sessionSelection";

const mocks = vi.hoisted(() => ({
  cards: [] as { id: string; tool_call_id: string; status: string }[],
}));

const tool = (id: string, status = "done") => ({
  type: "tool",
  tool: { id, name: "generate_speech", args: { text: id }, status, result: status === "done" ? { ok: true } : undefined },
});

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  api: vi.fn(async () => ({})),
  assetFileUrl: (id: string) => `/files/${id}`,
  assetPreviewUrl: (id: string) => `/previews/${id}`,
  assetThumbnailUrl: (id: string) => `/thumbs/${id}`,
  getAsset: vi.fn(async () => null),
  agentManifest: vi.fn(async () => ({ version: "1" })),
  listAgentTools: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", title: "配音", is_mine: true }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", title: "配音", status: "idle", is_mine: true })),
  listAgentMessages: vi.fn(async () => [
    { id: "u1", session_id: "s1", role: "user", content: "配三段", payload: {}, error: null, created_at: "2026-10-02T10:00:00" },
    { id: "m1", session_id: "s1", role: "assistant", content: "", error: null, created_at: "2026-10-02T10:01:00",
      payload: { timeline: [tool("a1"), tool("a2"), tool("a3", "error")] } },
    { id: "u2", session_id: "s1", role: "user", content: "后来的一句", payload: {}, error: null, created_at: "2026-10-02T10:02:00" },
  ]),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  listAgentQuestions: vi.fn(async () => []),
  listConfirmations: vi.fn(async (query: { status?: string }) =>
    mocks.cards
      .filter((card) => !query.status || card.status === query.status)
      .map((card) => ({
        workspace_id: "w1", session_id: "s1", tool: "generate_speech", permission: "ai-cost", summary: card.id, headline: card.id,
        warning: "", payload: {}, result: {}, error: null, requested_by: "pi-agent", decision_mode: "manual",
        created_at: "2026-10-02T10:00:30", resolved_at: null, ...card,
      })),
  ),
  approveConfirmation: vi.fn(),
  rejectConfirmation: vi.fn(),
  sendAgentMessage: vi.fn(),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));
vi.mock("@/features/agent/messageUsage", () => ({ MessageUsageFooter: () => null, MessageFooter: () => null, MessageTime: () => null }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear() {} }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_MESSAGE_CHARS: 1e6,
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
  documentText: () => "",
  emptyDocument: { type: "doc", content: [] },
}));
vi.mock("@/features/ai-studio/SessionList", () => ({ SessionList: () => null }));
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => null }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => null }));
vi.mock("@/features/agent/trace/TraceView", () => ({ TraceView: () => null, TraceStatsBar: () => null }));
vi.mock("@/features/agent/trace/traceModel", () => ({ buildTurns: () => [] }));

import { ChatWorkspace } from "./ChatWorkspace";

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem(agentSessionSelectionKey("w1"), "s1");
  vi.stubGlobal("ResizeObserver", NoopResizeObserver);
});

it("执行完的收成行里的状态,还在等的那张摆在它那次调用里、在后面的对话之前", async () => {
  mocks.cards = [
    { id: "c1", tool_call_id: "a1", status: "executed" },
    { id: "c2", tool_call_id: "a2", status: "executed" },
    { id: "c3", tool_call_id: "a3", status: "pending" },
  ];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <ChatWorkspace workspace={{ id: "w1", name: "工作区" } as never} />
    </QueryClientProvider>,
  );

  await waitFor(() =>
    expect(container.querySelector("article")?.closest("[data-tool-call]")?.getAttribute("data-tool-call")).toBe("a3"),
  );
  expect(container.querySelectorAll("article")).toHaveLength(1);
  expect(container.querySelectorAll("[data-decision='executed']")).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "confirmDismiss" })).toBeNull();
  const later = screen.getByText("后来的一句");
  expect(container.querySelector("article")!.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
