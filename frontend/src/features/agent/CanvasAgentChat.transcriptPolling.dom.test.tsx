/** @vitest-environment jsdom */

/**
 * 对话的消息只在一轮跑着的时候轮询(智能体那一路 AGENT-11 第一步)。
 *
 * 此前面板每 1.5 秒(AI Studio 每 1.2 秒)无条件整段重拉消息 —— 消息里带着每一轮的工具调用和完整结果,维护者库里最大
 * 一段 14 条消息 3.1 MB,停在那里不动也一直在下载、整段重渲。现在:空闲时不拉;会话的状态或 updated_at 一变(一轮
 * 开始 / 收尾)就重取一次;跑着的时候照常轮询。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  session: { id: "s1", workspace_id: "w1", title: "t", is_mine: true, status: "idle", home_kind: "note", home_id: "a", updated_at: "2026-10-08T00:00:00" },
  messages: [] as { id: string; session_id: string; role: string; content: string; payload: Record<string, unknown>; error: null; created_at: string }[],
}));

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  isNotFound: () => false,
  listAgentSessions: vi.fn(async () => [{ ...backend.session }]),
  getAgentSession: vi.fn(async () => ({ ...backend.session })),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  listAgentMessages: vi.fn(async () => backend.messages.map((one) => ({ ...one }))),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(),
  api: vi.fn(async () => ({})),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/api/domains/sessions", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  //: 流不在这条测试的范围里:一接就结束。
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
vi.mock("@/features/agent/QueuedMessages", () => ({ QueuedMessages: () => null }));

import { listAgentMessages } from "@/api/client";
import { CanvasAgentChat } from "./CanvasAgentChat";
import { adoptAgentSession } from "./sessionSelection";

const NOTE_A = { kind: "note", id: "a" } as const;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  window.sessionStorage.clear();
});

it("空闲时不拉消息;一轮收尾(updated_at 变了)重取一次;跑着的时候轮询", async () => {
  const fetched = vi.mocked(listAgentMessages);
  backend.messages = [{ id: "m1", session_id: "s1", role: "user", content: "第一句", payload: {}, error: null, created_at: "2026-10-08T00:00:00" }];
  adoptAgentSession("w1", NOTE_A, "s1");
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CanvasAgentChat contextLine="" emptyHint="hint" placeholder="p" rectKey="r" workspaceId="w1" place={NOTE_A} mode="docked" />
    </QueryClientProvider>,
  );
  await screen.findByText("第一句");
  const atRest = fetched.mock.calls.length;
  await sleep(3400);
  expect(fetched.mock.calls.length - atRest, "空闲时还在整段重拉消息").toBe(0);

  // 别处起了一轮又收了尾(比如任务回执):状态没赶上被看见,updated_at 变了 —— 重取一次,新消息出现。
  backend.messages.push({ id: "m2", session_id: "s1", role: "user", content: "回执处理完了", payload: {}, error: null, created_at: "2026-10-08T00:01:00" });
  backend.session = { ...backend.session, updated_at: "2026-10-08T00:01:00" };
  await screen.findByText("回执处理完了", undefined, { timeout: 4000 });

  backend.session = { ...backend.session, status: "running", updated_at: "2026-10-08T00:02:00" };
  await waitFor(() => expect(fetched.mock.calls.length).toBeGreaterThan(atRest + 1), { timeout: 4000 });
  const whileRunning = fetched.mock.calls.length;
  await sleep(3400);
  expect(fetched.mock.calls.length - whileRunning, "跑着的时候要轮询").toBeGreaterThanOrEqual(1);
}, 20_000);
