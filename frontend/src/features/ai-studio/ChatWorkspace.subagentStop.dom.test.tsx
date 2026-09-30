/** @vitest-environment jsdom */

/**
 * 看子代理的时候,父会话这一轮照样停得下来。
 *
 * 子代理视图不给输入框(子代理不接受续聊),而此前整块输入区连同「停止」一起不渲染 —— 注释说
 * 「它的进程已结束」,可子代理正是父会话**这一轮**派出去的,它还在跑时父会话也在 running,
 * 想停只能先退出子代理视图。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  status: "running",
  stopAgentSession: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  agentManifest: vi.fn(async () => ({ version: "1" })),
  listAgentTools: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", title: "父会话" }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", title: "父会话", status: mocks.status })),
  listAgentMessages: vi.fn(async () => []),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: mocks.stopAgentSession,
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear() {} }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
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
  ChatComposer: () => <textarea aria-label="composer" />,
  appendText: (doc: unknown) => doc,
  collectReferences: () => [],
  documentText: () => "",
  emptyDocument: { type: "doc", content: [] },
}));
vi.mock("@/features/ai-studio/SessionList", () => ({ SessionList: () => null }));
vi.mock("@/features/agent/ChatBubble", () => ({ ChatBubble: () => null }));
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => null }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => null }));
vi.mock("@/features/agent/PendingDecisions", () => ({ PendingDecisions: () => null }));
vi.mock("@/features/agent/QueuedMessages", () => ({ QueuedMessages: () => null }));
vi.mock("@/features/agent/trace/TraceView", () => ({ TraceView: () => null, TraceStatsBar: () => null }));
vi.mock("@/features/agent/trace/traceModel", () => ({ buildTurns: () => [] }));
vi.mock("@/features/agent/SubagentPanel", () => {
  const run = { call: { id: "call-1" }, running: true };
  return {
    collectSubagentRuns: () => [run],
    SubagentButton: ({ onOpen }: { onOpen: (value: typeof run) => void }) => (
      <button type="button" onClick={() => onOpen(run)}>
        open-subagent
      </button>
    ),
    SubagentBreadcrumb: () => <span>breadcrumb</span>,
    SubagentSessionView: () => <div>subagent-view</div>,
    InspectorSubagentList: () => null,
  };
});

import { ChatWorkspace } from "./ChatWorkspace";

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  window.localStorage.clear();
  mocks.stopAgentSession.mockReset().mockResolvedValue({});
  vi.stubGlobal("ResizeObserver", NoopResizeObserver);
  // 在跑的会话会去接流;这里不关心流,给一个立刻失败的响应。
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 503 })));
});

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChatWorkspace workspace={{ id: "w1", name: "工作区" } as never} />
    </QueryClientProvider>,
  );
  //: 等当前会话落定再点:换会话会退出子代理视图,清单到达那一下就是一次「换会话」。
  await screen.findByText("父会话");
}

it("父会话在跑:子代理视图底部有「父会话运行中 · 停止」,停的是父会话;没有输入框", async () => {
  mocks.status = "running";
  await mount();
  fireEvent.click(await screen.findByRole("button", { name: "open-subagent" }));
  expect(await screen.findByText("subagent-view")).toBeTruthy();
  expect(screen.queryByLabelText("composer")).toBeNull();

  expect(await screen.findByText("chatParentRunning")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "chatStop" }));
  await waitFor(() => expect(mocks.stopAgentSession).toHaveBeenCalledWith("s1"));
});

it("父会话已经停了:子代理视图里不留停止条", async () => {
  mocks.status = "idle";
  await mount();
  fireEvent.click(await screen.findByRole("button", { name: "open-subagent" }));
  expect(await screen.findByText("subagent-view")).toBeTruthy();
  expect(screen.queryByText("chatParentRunning")).toBeNull();
  expect(screen.queryByRole("button", { name: "chatStop" })).toBeNull();
});
