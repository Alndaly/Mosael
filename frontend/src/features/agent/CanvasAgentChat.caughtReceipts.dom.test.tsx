/** @vitest-environment jsdom */

/**
 * 被智能体**接住**的回执不在画布助手侧栏里单独占一条消息 —— 它收进接住它的那一轮回答的步骤里。
 *
 * 画布助手自己 map 消息(不走 ChatBubble),所以接线也只能在它自己的 map 里做。AI 工作台走
 * ChatBubble,另有一条同款测试 —— 两个入口对同一份回执给出两种位置,用户没法预期哪一种才是对的。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { adoptAgentSession } from "@/features/agent/sessionSelection";

const h = vi.hoisted(() => ({ messages: [] as Array<Record<string, unknown>> }));

const message = (id: string, role: string, content: string, payload: Record<string, unknown> = {}) => ({
  id, session_id: "s1", role, content, payload, error: null, created_at: "2026-10-18T00:00:00",
});

/** 一个字面意义上的「接住了」:回执之后有一条正常回答。 */
const caught = message("r1", "job_receipt", "「配音 1」失败了。", {
  job_id: "j1", kind: "tts", status: "failed", subject: "配音 1", error_summary: "下载成片时断了",
});
const answer = message("a1", "assistant", "配音 1 已经好了", {
  timeline: [{ type: "text", text: "配音 1 已经好了" }],
});
const firstAsk = message("u1", "user", "把旁白都配上音");
/** 没接住:还压在 waiting 里,没人读过。 */
const undelivered = message("r2", "job_receipt", "「配音 2」失败了。", {
  job_id: "j2", kind: "tts", status: "failed", subject: "配音 2", undelivered: true, error_summary: "合成时断了",
});

const CATALOG = {
  kinds: [{ kind: "tts", label: "配音", announce: "always", affects: ["assets"], view: "ai", record_field: "session_id" }],
  fallback: { kind: "", label: "任务", announce: "always", affects: [], view: null, record_field: null },
};

vi.mock("@/api/client", () => ({
  isNotFound: () => false,
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  assetFileUrl: (id: string) => `/files/${id}`,
  assetPreviewUrl: (id: string) => `/previews/${id}`,
  assetThumbnailUrl: (id: string) => `/thumbs/${id}`,
  getAsset: vi.fn(async () => null),
  fetchJobKinds: vi.fn(async () => CATALOG),
  getJob: vi.fn(async () => null),
  cancelJob: vi.fn(),
  listJobEvents: vi.fn(async () => []),
  listJobChildren: vi.fn(async () => []),
  regenerateAssetProxy: vi.fn(),
  listAgentSessions: vi.fn(async () => [
    { id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "配音", is_mine: true },
  ]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({
    id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok",
    title: "配音", status: "idle", is_mine: true,
  })),
  listAgentMessages: vi.fn(async () => h.messages),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  listAgentQuestions: vi.fn(async () => []),
  listConfirmations: vi.fn(async () => []),
  approveConfirmation: vi.fn(),
  rejectConfirmation: vi.fn(),
  sendAgentMessage: vi.fn(),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));
vi.mock("@/features/agent/useAgentTurnStream", () => ({
  useAgentTurnStream: () => ({ streamText: "", streamTimeline: [], attach: async () => {} }),
}));
vi.mock("@/features/agent/messageUsage", () => ({ MessageUsageFooter: () => null, MessageFooter: () => null, MessageTime: () => null }));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_CONTEXT_CHARS: 1e6,
  MAX_MESSAGE_CHARS: 1e6,
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

import { CanvasAgentChat } from "./CanvasAgentChat";

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CanvasAgentChat
        contextLine=""
        emptyHint="empty"
        placeholder="placeholder"
        rectKey="test.canvas.agent"
        workspaceId="w1"
        place={{ kind: "studio", id: "" }}
        mode="docked"
        onModeChange={() => {}}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.stubGlobal("ResizeObserver", NoopResizeObserver);
  adoptAgentSession("w1", { kind: "studio", id: "" }, "s1");
});

it("被接住的回执不单独渲染:收进那一轮的步骤里,默认收起、展开看得到", async () => {
  h.messages = [firstAsk, caught, answer];
  const { container } = mount();

  await screen.findByText("配音 1 已经好了");
  //: 回执单独那一条已经不在了 —— 对话里留的是结论(智能体那句话)。
  await waitFor(() => expect(container.querySelectorAll("[data-job-receipt]")).toHaveLength(0));
  //: 收进过程摘要里,默认收起:收起时连那一行都不在 DOM 里。
  const summary = screen.getByRole("button", { name: /agentProcessDone/ });
  expect(summary.getAttribute("aria-expanded")).toBe("false");
  expect(container.querySelector("[data-receipt-step]")).toBeNull();

  fireEvent.click(summary);
  const step = container.querySelector<HTMLElement>("[data-receipt-step='j1']");
  expect(step).toBeTruthy();
  expect(step?.textContent).toContain("配音");
  expect(step?.textContent).toContain("配音 1");
  expect(step?.textContent).toContain("runStatus_failed");
});

it("没接住的回执仍然显式是一张卡,带动作", async () => {
  h.messages = [firstAsk, undelivered];
  const { container } = mount();

  await screen.findByText("配音 2");
  const notices = container.querySelectorAll<HTMLElement>("[data-job-receipt]");
  expect(notices).toHaveLength(1);
  expect(notices[0].textContent).toContain("chatReceiptWaiting");
  expect(notices[0].querySelector("[data-receipt-open-task]")).toBeTruthy();
});
