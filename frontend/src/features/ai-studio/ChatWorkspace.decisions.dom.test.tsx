/** @vitest-environment jsdom */

/**
 * AI 工作台的对话和画布助手是同一套确认卡:卡摆在发起它的那次工具调用里,决定之后收成那一行的状态。
 * 两个入口各渲染各的消息列表(这边走 ChatBubble),所以各钉一条 —— 只在一边接上 provider 的话,
 * 另一边的卡会悄悄退回列表末尾(那正是这次要改掉的样子),而什么都不会报错。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { adoptAgentSession } from "@/features/agent/sessionSelection";

const mocks = vi.hoisted(() => ({
  cards: [] as { id: string; tool_call_id: string; status: string }[],
}));

const tool = (id: string, status = "done") => ({
  type: "tool",
  tool: { id, name: "generate_speech", args: { text: id }, status, result: status === "done" ? { ok: true } : undefined },
});

/**
 * 默认的对话。**每一条用例开始前都要回到这一份**:第二条用例改写过 `listAgentMessages` 的
 * 返回值却从不还原,乱序跑时它先跑,第一条就吃到别人的消息、找不到 `a3` 而红
 * (CI 的 `test / frontend` 就是被这个弄红的,顺序一变就复现)。
 */
const DEFAULT_MESSAGES = () => [
  { id: "u1", session_id: "s1", role: "user", content: "配三段", payload: {}, error: null, created_at: "2026-10-02T10:00:00" },
  { id: "m1", session_id: "s1", role: "assistant", content: "", error: null, created_at: "2026-10-02T10:01:00",
    payload: { timeline: [tool("a1"), tool("a2"), tool("a3", "error")] } },
  { id: "u2", session_id: "s1", role: "user", content: "后来的一句", payload: {}, error: null, created_at: "2026-10-02T10:02:00" },
];

vi.mock("@/api/client", () => ({
  isNotFound: () => false,
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  api: vi.fn(async () => ({})),
  assetFileUrl: (id: string) => `/files/${id}`,
  assetPreviewUrl: (id: string) => `/previews/${id}`,
  assetThumbnailUrl: (id: string) => `/thumbs/${id}`,
  getAsset: vi.fn(async () => null),
  agentManifest: vi.fn(async () => ({ version: "1" })),
  listAgentTools: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "配音", is_mine: true }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "配音", status: "idle", is_mine: true })),
  listAgentMessages: vi.fn(async () => DEFAULT_MESSAGES()),
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
import { listAgentMessages } from "@/api/client";

class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  // 每条用例都从这一份开始:上一条改过 `listAgentMessages` 的话,乱序跑会互相污染。
  vi.mocked(listAgentMessages).mockResolvedValue(DEFAULT_MESSAGES() as never);
  mocks.cards = [];
  window.localStorage.clear();
  window.sessionStorage.clear();
  adoptAgentSession("w1", { kind: "studio", id: "" }, "s1");
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

  //: **等到真的挂上来**,别按 `waitFor` 的 1 秒默认值赌:这条用例在某次乱序跑里首帧花了 4 秒
  //: (CI 上就是它把 `test / frontend` 弄红的),而渲染本身没有任何问题。
  await waitFor(
    () =>
      expect(container.querySelector("article")?.closest("[data-tool-call]")?.getAttribute("data-tool-call")).toBe("a3"),
    { timeout: 8000 },
  );
  expect(container.querySelectorAll("article")).toHaveLength(1);
  expect(container.querySelectorAll("[data-decision='executed']")).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "confirmDismiss" })).toBeNull();
  const later = screen.getByText("后来的一句");
  expect(container.querySelector("article")!.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

/**
 * 答完的选择:**回执那条消息不画成气泡**,答案只在 `ask_user` 的工具卡里。
 *
 * 维护者:「**我的选择不应该作为一个消息卡片 这个就显示在 ask_user 的那个工具卡片内即可**」✓。
 * 后端仍然要把答案拼成一句话发回去(模型读的是它)✓ —— 那是协议,不是界面。
 * 两个入口是同一条规矩(这边走 ChatBubble),所以两边各钉一次。
 */
it("回执那条不画成消息,答案在 ask_user 卡里", async () => {
  vi.mocked(listAgentMessages).mockResolvedValue([
    { id: "u1", session_id: "s1", role: "user", content: "开工", payload: {}, error: null, created_at: "2026-10-02T10:00:00" },
    { id: "m1", session_id: "s1", role: "assistant", content: "", error: null, created_at: "2026-10-02T10:00:30",
      payload: { timeline: [{ type: "tool", tool: { id: "ask", name: "ask_user", status: "done",
        result: { content: [{ type: "text", text: "" }], details: { data: { status: "answered", answers: { "接下来怎么走？": ["先暂停"] }, question_id: "q1" } } } } }] } },
    { id: "u2", session_id: "s1", role: "user", content: "我选好了:\n· 接下来怎么走？:先暂停", error: null, created_at: "2026-10-02T10:01:00",
      payload: { answers: { question_id: "q1", picked: [{ question: "接下来怎么走？", choices: ["先暂停"] }] } } },
  ] as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <ChatWorkspace workspace={{ id: "w1", name: "工作区" } as never} />
    </QueryClientProvider>,
  );

  // 等这一轮挂上来(有工具卡就说明消息都在了)。
  await waitFor(() => expect(container.querySelector("[data-tool-call='ask']")).toBeTruthy());
  // 回执那条**不渲染**:既没有记录卡,也没有"我选好了…"那段自述。
  expect(container.querySelector("[data-answer-record]")).toBeNull();
  expect(container.textContent).not.toContain("我选好了");
  // 答案由工具卡承担:展开后那一行状态里有它。
  const card = container.querySelector("[data-tool-call='ask']") as HTMLElement;
  fireEvent.click(within(card).getByRole("button"));
  await waitFor(() => expect(card.querySelector("[data-answer-status]")).toBeTruthy());
  expect(card.textContent).toContain("先暂停");
});
