/** @vitest-environment jsdom */

/**
 * 后台任务的回执画成任务通知,不进「待发消息」那一条条。
 *
 * 用户截图(剪辑页侧栏):智能体连着提交一串配音,每条跑完的回执都以用户消息的样子排进了输入框上方的队列,
 * 带着 Steer 和删除 —— 「明明是任务的返回,但有一瞬间会显示在消息队列中」「全都在消息队列中了」。
 * 回执现在是自己的角色(job_receipt):
 *   · 画成对话里的一行任务通知,不是用户气泡,没有 Steer / 删除;
 *   · 还没交给智能体的(undelivered)画在正在跑的那一轮**下面** —— 这一轮结束它才交出去,交出去之后
 *     对话也是这个顺序,不会跳位;
 *   · 用户自己排的话照旧在队列里。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { adoptAgentSession } from "@/features/agent/sessionSelection";

const message = (id: string, role: string, content: string, payload: Record<string, unknown> = {}) => ({
  id, session_id: "s1", role, content, payload, error: null, created_at: "2026-10-02T10:00:00",
});

const queued = message("q1", "user", "顺便把音量调大一点", { queued: true, queued_by: "me" });

const CATALOG = {
  kinds: [
    { kind: "ai_generation", label: "生成", announce: "always", affects: ["assets"], view: "ai", record_field: "session_id" },
    { kind: "tts", label: "配音", announce: "always", affects: ["assets"], view: "ai", record_field: "session_id" },
  ],
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
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "配音", is_mine: true }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "配音", status: "running", is_mine: true })),
  listAgentMessages: vi.fn(async () => [
    message("u1", "user", "把五段旁白都配上音"),
    message("m1", "assistant", "先配第一段", { timeline: [{ type: "text", text: "先配第一段" }] }),
    message("r1", "job_receipt", "「配音 1」失败了。", {
      job_id: "j1", status: "failed", kind: "ai_generation", subject: "配音 1",
      error: "下载成片时断了", error_summary: "下载成片时断了",
    }),
    queued,
    message("r2", "job_receipt", "「配音 2」已取消。", {
      job_id: "j2", status: "cancelled", kind: "tts", subject: "配音 2", undelivered: true, deliver_as: "me",
    }),
  ]),
  listAgentQueue: vi.fn(async () => [queued]),
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
  useAgentTurnStream: () => ({
    streamText: "在配第三段",
    streamTimeline: [{ type: "text", text: "在配第三段" }],
    attach: async () => {},
  }),
}));
vi.mock("@/features/agent/messageUsage", () => ({ MessageUsageFooter: () => null }));
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

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", NoopResizeObserver);
  window.localStorage.clear();
  window.sessionStorage.clear();
  adoptAgentSession("w1", { kind: "studio", id: "" }, "s1");
});

async function mount(extra: { showJobReceipts?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
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
        {...extra}
      />
    </QueryClientProvider>,
  );
  await screen.findByText("把五段旁白都配上音");
  return view;
}

const follows = (a: Node, b: Node) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

it("回执画成任务通知,不进待发消息那一条条;用户自己排的那条照旧在", async () => {
  const { container } = await mount();
  await waitFor(() => expect(screen.getAllByText("chatSteerAction")).toHaveLength(1));

  const notices = [...container.querySelectorAll("[data-job-receipt]")];
  expect(notices).toHaveLength(2);
  //: 失败是一条卡(原因 + 能点的动作),被停下的是灰的「已停止」;都不是一行正文。
  expect(notices[0].textContent).toContain("下载成片时断了");
  expect(notices[1].textContent).toContain("genStopped");

  //: 待发那一条条里只有用户自己排的话。
  const steer = screen.getByText("chatSteerAction").closest("div")!;
  expect(steer.textContent).toContain("顺便把音量调大一点");
  expect(container.querySelectorAll("[data-job-receipt]")).toHaveLength(2);
  expect(steer.textContent).not.toContain("genStopped");
});

it("工作台助手列不显示后台任务回执:任务由运行面板和任务中心承担", async () => {
  const { container } = await mount({ showJobReceipts: false });
  await screen.findByText("在配第三段");
  expect(container.querySelectorAll("[data-job-receipt]")).toHaveLength(0);
  expect(screen.queryByText("下载成片时断了")).toBeNull();
  expect(screen.getByText("把五段旁白都配上音")).toBeTruthy();
});

it("还没交给智能体的回执画在正在跑的那一轮下面;交过的按时间排在前面", async () => {
  const { container } = await mount();
  const live = await screen.findByText("在配第三段");
  const [delivered, waiting] = [...container.querySelectorAll("[data-job-receipt]")];

  expect(follows(delivered, live)).toBe(true);
  expect(follows(live, waiting)).toBe(true);
  expect(waiting.textContent).toContain("chatReceiptWaiting");
  expect(delivered.textContent).not.toContain("chatReceiptWaiting");
});
