/** @vitest-environment jsdom */

/**
 * 页面给面板的上下文可以是一个函数:**发送那一刻**才取。笔记页的正文和选区每敲一个字都在变 ——
 * 渲染时取的话,发出去的是上一次重渲时的样子;为了它每个字都重渲整页又不值。
 * 页面挂进来的小条(笔记页:选中的那段)和附件排在同一排。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { agentSessionSelectionKey } from "@/features/agent/sessionSelection";

const mocks = vi.hoisted(() => ({
  sendAgentMessage: vi.fn(async () => ({ id: "m1" })),
  clearNotes: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", title: "对话", is_mine: true }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", title: "对话", status: "idle", is_mine: true })),
  listAgentMessages: vi.fn(async () => []),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: mocks.sendAgentMessage,
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear: mocks.clearNotes }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_CONTEXT_CHARS: 4000,
  MAX_MESSAGE_CHARS: 8000,
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true,
    files: [],
    media: [],
    chips: [],
    uploading: false,
    previewModal: null,
    onPaste() {},
    drop: { handlers: {}, overlay: null },
    accept() {},
    clear() {},
  }),
}));
vi.mock("@/features/agent/ChatComposer", () => ({
  ChatComposer: ({ focusSignal }: { focusSignal?: number }) => <textarea aria-label="composer" data-focus-signal={focusSignal ?? 0} />,
  appendText: (doc: unknown) => doc,
  collectReferences: () => [],
  documentText: () => "改写这段",
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

import { CanvasAgentChat } from "./CanvasAgentChat";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  window.localStorage.clear();
  window.localStorage.setItem(agentSessionSelectionKey("w1"), "s1");
  mocks.sendAgentMessage.mockClear();
  mocks.clearNotes.mockClear();
});

it("上下文给成函数:发送那一刻才取;页面的小条和附件一排,焦点信号交给输入框", async () => {
  let page = "渲染时的上下文";
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CanvasAgentChat
        contextLine={() => page}
        contextChips={[{ id: "sel", label: "选中的那段", icon: null, onRemove() {} }]}
        messageQuote={{ kind: "note", note_id: "n1", title: "周报", text: "选中的那段", start: 3 }}
        focusSignal={2}
        emptyHint="empty"
        placeholder="placeholder"
        rectKey="test.canvas.agent"
        workspaceId="w1"
        mode="docked"
        onModeChange={() => {}}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
  await screen.findByText("对话");
  expect(screen.getByText("选中的那段")).toBeInTheDocument();
  expect(screen.getByLabelText("composer")).toHaveAttribute("data-focus-signal", "2");

  page = "发送那一刻的上下文";
  fireEvent.click(screen.getByRole("button", { name: "chatSend" }));

  await waitFor(() => expect(mocks.sendAgentMessage).toHaveBeenCalled());
  const [sessionId, body] = mocks.sendAgentMessage.mock.calls[0] as unknown as [string, { context: string; content: string }];
  expect(sessionId).toBe("s1");
  expect(body.content).toBe("改写这段");
  expect(body.context).toBe("发送那一刻的上下文");
  //: 页面给的摘录跟着这条消息落库(payload.quote),气泡里画出可点的一行。
  expect((body as unknown as { quote: unknown }).quote).toEqual({ kind: "note", note_id: "n1", title: "周报", text: "选中的那段", start: 3 });
});

it("页面投递的一条(选区工具条上的 AI 动作):当场发出去,带上页面上下文和动作说明;不动输入框;发完告诉页面", async () => {
  const taken = vi.fn();
  const sent = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CanvasAgentChat
        contextLine={() => "这一篇笔记的上下文"}
        messageQuote={{ kind: "note", note_id: "n1", title: "周报", text: "选中的那段", start: 3 }}
        outbox={{ id: 7, text: "润色选中的这段", context: "这是选区工具条上的「润色」" }}
        onOutboxTaken={taken}
        onSent={sent}
        emptyHint="empty"
        placeholder="placeholder"
        rectKey="test.canvas.agent"
        workspaceId="w1"
        mode="docked"
        onModeChange={() => {}}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );

  await waitFor(() => expect(mocks.sendAgentMessage).toHaveBeenCalledTimes(1));
  expect(taken).toHaveBeenCalledTimes(1);
  const [, body] = mocks.sendAgentMessage.mock.calls[0] as unknown as [string, { content: string; context: string; quote: unknown }];
  expect(body.content).toBe("润色选中的这段");
  expect(body.context).toBe("这一篇笔记的上下文\n\n这是选区工具条上的「润色」");
  expect(body.quote).toEqual({ kind: "note", note_id: "n1", title: "周报", text: "选中的那段", start: 3 });
  await waitFor(() => expect(sent).toHaveBeenCalled());
  //: 输入框里挂着的笔记引用不是这一条的,不该被它带走、也不该被清掉。
  expect(mocks.clearNotes).not.toHaveBeenCalled();
});
