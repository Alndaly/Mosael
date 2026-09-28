/** @vitest-environment jsdom */

/**
 * 画布助手(工作流 / 画板 / 剪辑 / 3D 共用)和 AI 工作台同一条规矩:同事共享来的对话**只能看**。
 * 输入卡整张换成只读说明(模型、会话设置都在里面),拍板的卡只给看。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { agentSessionSelectionKey } from "@/features/agent/sessionSelection";

const mocks = vi.hoisted(() => ({
  isMine: false,
  pendingDecisions: vi.fn((_props: { readOnly?: boolean }) => null),
}));

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", title: "同事的脚本讨论", is_mine: mocks.isMine }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", title: "同事的脚本讨论", status: "idle", is_mine: mocks.isMine })),
  listAgentMessages: vi.fn(async () => []),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(),
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
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true,
    files: [],
    media: [],
    chips: [],
    uploading: false,
    previewModal: null,
    onPaste() {},
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
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => <span>model-picker</span> }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => <span>session-settings</span> }));
vi.mock("@/features/agent/PendingDecisions", () => ({ PendingDecisions: mocks.pendingDecisions }));
vi.mock("@/features/agent/QueuedMessages", () => ({ QueuedMessages: () => null }));

import { CanvasAgentChat } from "./CanvasAgentChat";

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", NoopResizeObserver);
  window.localStorage.clear();
  // 共享来的那条只在**点开过**时才是当前会话(没选过时回落只落在自己的对话上)。
  window.localStorage.setItem(agentSessionSelectionKey("w1"), "s1");
  mocks.pendingDecisions.mockClear();
});

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CanvasAgentChat
        contextLine=""
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
  await screen.findByText("同事的脚本讨论");
}

it("共享来的对话:输入卡换成只读说明,模型与会话设置不出现,拍板的卡只给看", async () => {
  mocks.isMine = false;
  await mount();
  expect(await screen.findByRole("note")).toHaveTextContent("chatSessionReadOnly");
  expect(screen.queryByLabelText("composer")).toBeNull();
  expect(screen.queryByText("model-picker")).toBeNull();
  expect(screen.queryByText("session-settings")).toBeNull();
  expect(mocks.pendingDecisions).toHaveBeenCalled();
  expect(mocks.pendingDecisions.mock.calls.every(([props]) => props.readOnly === true)).toBe(true);
});

it("自己的对话:输入卡照常", async () => {
  mocks.isMine = true;
  await mount();
  expect(await screen.findByLabelText("composer")).toBeTruthy();
  expect(screen.getByText("model-picker")).toBeTruthy();
  expect(screen.queryByRole("note")).toBeNull();
});
