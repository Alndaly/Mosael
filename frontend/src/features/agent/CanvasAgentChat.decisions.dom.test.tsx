/** @vitest-environment jsdom */

/**
 * 「智能体请求」卡跟着对话走,决定之后收成那次工具调用里的一行状态。
 *
 * 用户截图(剪辑页侧栏):同一轮里智能体连着请求了五条以上「生成音频: <一句旁白>」(每条带「AI 成本」),全批了、
 * 全「✓ 已执行」,结果五张大卡(各带 ×)一张接一张堆在那一轮的 update_plan / create_project / list_assets
 * 工具行和「已用 2m 20s」状态行**下面**、输入框上面,把对话往上顶,「有新内容」按钮压在卡上。用户原话:
 * 「智能体审批通过后那个卡片不需要继续保留着的」「智能体请求卡片不应固定在这里的,应该跟随聊天过程才对」
 * 「智能体请求结果也是」。
 *
 * 判据:
 *   · 等决定的卡渲染在**发起它的那次工具调用**里(按 tool_call_id 对上),不在列表末尾;
 *   · 批准并执行 / 拒绝 / 失败之后,任何地方都不再有那张卡,只在那次调用的行里有一行状态;没有 ×;
 *   · 失败的那一行带着原因;
 *   · 对不上任何一行的待决卡(那一行还没到屏上)照样看得见,不会因为找不到位置就消失。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { adoptAgentSession } from "@/features/agent/sessionSelection";

type Card = {
  id: string;
  tool_call_id: string | null;
  status: string;
  error?: string | null;
  decision_mode?: string;
};

const mocks = vi.hoisted(() => ({
  running: true,
  messages: [] as unknown[],
  streamTimeline: [] as unknown[],
  cards: [] as Card[],
  approve: vi.fn(),
}));

function confirmation(card: Card) {
  return {
    workspace_id: "w1",
    session_id: "s1",
    tool: "generate_speech",
    permission: "ai-cost",
    summary: `生成音频: ${card.id}`,
    headline: `生成音频: ${card.id}`,
    warning: "",
    summary_key: "",
    summary_params: {},
    payload: { text: card.id },
    result: {},
    error: null,
    requested_by: "pi-agent",
    decision_mode: "manual",
    decided_by: null,
    created_at: "2026-10-02T10:00:00",
    resolved_at: null,
    ...card,
  };
}

vi.mock("@/api/client", () => ({
  isNotFound: () => false,
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  assetFileUrl: (id: string) => `/files/${id}`,
  assetPreviewUrl: (id: string) => `/previews/${id}`,
  assetThumbnailUrl: (id: string) => `/thumbs/${id}`,
  getAsset: vi.fn(async () => null),
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "配音", is_mine: true }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(async () => ({})),
  deleteAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({
    id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "配音", status: mocks.running ? "running" : "idle", is_mine: true, auto_allow_tools: [],
  })),
  listAgentMessages: vi.fn(async () => mocks.messages),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  listAgentQuestions: vi.fn(async () => []),
  answerAgentQuestion: vi.fn(),
  dismissAgentQuestion: vi.fn(),
  listConfirmations: vi.fn(async (query: { status?: string }) =>
    mocks.cards.filter((card) => !query.status || card.status === query.status).map(confirmation),
  ),
  approveConfirmation: (id: string) => mocks.approve(id),
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
    streamText: mocks.streamTimeline.length ? "x" : "",
    streamTimeline: mocks.streamTimeline,
    attach: async () => {},
  }),
}));
vi.mock("@/features/agent/messageUsage", () => ({ MessageUsageFooter: () => null }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear() {}, selected: [], restore() {} }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_CONTEXT_CHARS: 1e6,
  MAX_MESSAGE_CHARS: 1e6,
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
    clear() {}, restore() {},
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

const tool = (id: string, name: string, status = "done") => ({
  type: "tool",
  tool: { id, name, args: { text: id }, status, result: status === "done" ? { ok: true } : undefined },
});

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", NoopResizeObserver);
  window.localStorage.clear();
  window.sessionStorage.clear();
  adoptAgentSession("w1", { kind: "studio", id: "" }, "s1");
  mocks.running = true;
  mocks.messages = [{ id: "u1", session_id: "s1", role: "user", content: "给每段旁白配音", payload: {}, error: null, created_at: "2026-10-02T09:59:00" }];
  mocks.streamTimeline = [];
  mocks.cards = [];
  mocks.approve.mockReset();
});

async function mount() {
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
      />
    </QueryClientProvider>,
  );
  await screen.findByText("配音");
  return view;
}

const row = (container: HTMLElement, id: string) => container.querySelector(`[data-tool-call="${id}"]`);

describe("一轮里连着五条「生成音频」,全批了、全执行完(用户截图那一幕)", () => {
  it("不留任何一张卡,也没有 × —— 每次调用的行里一行「已批准 · 已执行」", async () => {
    const audio = ["a1", "a2", "a3", "a4", "a5"];
    mocks.streamTimeline = [
      tool("p", "update_plan"),
      tool("c", "create_project"),
      tool("l", "list_assets"),
      ...audio.map((id) => tool(id, "generate_speech")),
    ];
    mocks.cards = audio.map((id) => ({ id: `card-${id}`, tool_call_id: id, status: "executed" }));
    const { container } = await mount();

    await waitFor(() => expect(container.querySelectorAll("[data-decision]")).toHaveLength(audio.length));
    for (const id of audio) {
      const line = row(container, id)!.querySelector("[data-decision]")!;
      expect(line.getAttribute("data-decision")).toBe("executed");
      expect(line.textContent).toContain("confirmDecisionManual");
      expect(line.textContent).toContain("confirmOutcomeExecuted");
    }
    expect(container.querySelector("article")).toBeNull();
    expect(screen.queryByRole("button", { name: "confirmDismiss" })).toBeNull();
    //: 不读的三步(update_plan 那几行)没有卡,也就没有状态行。
    expect(row(container, "p")!.querySelector("[data-decision]")).toBeNull();
  });

  it("前四条执行完、第五条还在等:只有第五条的卡,摆在第五次调用的位置", async () => {
    mocks.streamTimeline = [tool("l", "list_assets"), ...["a1", "a2", "a3", "a4"].map((id) => tool(id, "generate_speech")),
      tool("a5", "generate_speech", "running")];
    mocks.cards = [
      ...["a1", "a2", "a3", "a4"].map((id) => ({ id: `card-${id}`, tool_call_id: id, status: "executed" })),
      { id: "card-a5", tool_call_id: "a5", status: "pending" },
    ];
    const { container } = await mount();

    await waitFor(() => expect(container.querySelectorAll("article")).toHaveLength(1));
    const card = container.querySelector("article")!;
    expect(card.closest("[data-tool-call]")?.getAttribute("data-tool-call")).toBe("a5");
    expect(card.getAttribute("data-status")).toBe("pending");
    expect(container.querySelectorAll("[data-decision='executed']")).toHaveLength(4);
  });
});

it("等决定的卡在它那次调用里,不在列表末尾 —— 后面的对话排在它下面", async () => {
  /* 卡停在一轮早先的那一步(那一轮被停掉了,卡还没人管):它该留在那一步,而不是跑到最新那条消息后面。 */
  mocks.running = false;
  mocks.messages = [
    ...mocks.messages,
    { id: "m1", session_id: "s1", role: "assistant", content: "", error: null, created_at: "2026-10-02T10:00:00",
      payload: { timeline: [tool("h1", "generate_speech", "error"), { type: "text", text: "先停在这儿" }] } },
    { id: "u2", session_id: "s1", role: "user", content: "后来又问了一句", payload: {}, error: null, created_at: "2026-10-02T10:01:00" },
    { id: "m2", session_id: "s1", role: "assistant", content: "答", error: null, created_at: "2026-10-02T10:01:30",
      payload: { timeline: [{ type: "text", text: "后来的回答" }] } },
  ];
  mocks.cards = [{ id: "card-h1", tool_call_id: "h1", status: "pending" }];
  const { container } = await mount();

  const card = await waitFor(() => {
    const found = container.querySelector("article");
    expect(found?.closest("[data-tool-call]")?.getAttribute("data-tool-call")).toBe("h1");
    return found!;
  });
  expect(container.querySelectorAll("article")).toHaveLength(1);
  const later = screen.getByText("后来又问了一句");
  expect(card.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("批准之后卡就收起:那一行变成「已批准 · 已执行」,没有 ×", async () => {
  mocks.streamTimeline = [tool("a1", "generate_speech", "running")];
  mocks.cards = [{ id: "card-a1", tool_call_id: "a1", status: "pending" }];
  mocks.approve.mockImplementation(async (id: string) => {
    mocks.cards = [{ id, tool_call_id: "a1", status: "executed" }];
    return confirmation(mocks.cards[0]);
  });
  const { container } = await mount();

  //: 会话状态读回来之前流还算不上「这一轮」,卡先退在末尾;读回来之后才进到那一行里 —— 点的要是那一张。
  const card = await waitFor(() => {
    const found = row(container, "a1")?.querySelector("article");
    expect(found).toBeTruthy();
    return found!;
  });
  fireEvent.click(within(card as HTMLElement).getByRole("button", { name: /confirmAllowOnce/ }));

  await waitFor(() => expect(container.querySelector("article")).toBeNull());
  expect(mocks.approve).toHaveBeenCalledWith("card-a1");
  const line = row(container, "a1")!.querySelector("[data-decision]")!;
  expect(line.getAttribute("data-decision")).toBe("executed");
  expect(screen.queryByRole("button", { name: "confirmDismiss" })).toBeNull();
});

it("执行失败:那一行写明失败原因", async () => {
  mocks.streamTimeline = [tool("a1", "generate_speech", "error")];
  mocks.cards = [{ id: "card-a1", tool_call_id: "a1", status: "failed", error: "磁盘满了" }];
  const { container } = await mount();

  await waitFor(() => expect(row(container, "a1")!.querySelector("[data-decision='failed']")).toBeTruthy());
  const line = row(container, "a1")!.querySelector("[data-decision='failed']")!;
  expect(line.textContent).toContain("confirmOutcomeFailed");
  expect(row(container, "a1")!.textContent).toContain("磁盘满了");
  expect(container.querySelector("article")).toBeNull();
});

it("拒绝 / 作废:一行「已拒绝」「这一轮已停止,卡已作废」,不是卡,也不标红", async () => {
  mocks.streamTimeline = [
    tool("a1", "generate_speech", "error"),
    tool("a2", "generate_speech", "error"),
    tool("a3", "generate_speech", "error"),
    tool("a4", "generate_speech", "error"),
  ];
  mocks.cards = [
    { id: "card-a1", tool_call_id: "a1", status: "rejected" },
    //: 这一轮结束时后端把它还在等的卡结成 expired,error 里是由头的码(ADR 0007 修订 2026-10-08)。
    { id: "card-a2", tool_call_id: "a2", status: "expired", error: "turn_stopped" },
    { id: "card-a3", tool_call_id: "a3", status: "expired", error: "wait_timeout" },
    { id: "card-a4", tool_call_id: "a4", status: "expired", error: "turn_failed" },
  ];
  const { container } = await mount();

  await waitFor(() => expect(container.querySelectorAll("[data-decision]")).toHaveLength(4));
  expect(row(container, "a1")!.querySelector("[data-decision]")!.textContent).toContain("confirmStatusRejected");
  expect(row(container, "a2")!.querySelector("[data-decision]")!.textContent).toContain("confirmExpiredTurnStopped");
  expect(row(container, "a3")!.querySelector("[data-decision]")!.textContent).toContain("confirmExpiredWaitTimeout");
  expect(row(container, "a4")!.querySelector("[data-decision]")!.textContent).toContain("confirmExpiredTurnEnded");
  // 作废的卡不再给按钮,行上也不摆那个码。
  expect(container.querySelector("article")).toBeNull();
  expect(screen.queryByRole("button", { name: "confirmAllowOnce" })).toBeNull();
  expect(container.textContent).not.toContain("turn_stopped");
});

it("自动放行的那几张写「自动放行」,不冒充用户点过", async () => {
  mocks.streamTimeline = [tool("a1", "generate_speech")];
  mocks.cards = [{ id: "card-a1", tool_call_id: "a1", status: "executed", decision_mode: "session-allow" }];
  const { container } = await mount();

  await waitFor(() => expect(row(container, "a1")!.querySelector("[data-decision]")).toBeTruthy());
  expect(row(container, "a1")!.querySelector("[data-decision]")!.textContent).toContain("confirmDecisionAuto");
});

it("对不上任何一行的待决卡照样摆出来 —— 那一行还没到屏上,卡不能跟着看不见", async () => {
  mocks.streamTimeline = [tool("a1", "generate_speech")];
  mocks.cards = [{ id: "card-x", tool_call_id: "not-on-screen", status: "pending" }];
  const { container } = await mount();

  await waitFor(() => expect(container.querySelectorAll("article")).toHaveLength(1));
  expect(container.querySelector("article")!.closest("[data-tool-call]")).toBeNull();
});

it("等卡时按了停止:这一轮收尾,那一行收成「这一轮已停止,卡已作废」,不退回成工具的「失败」", async () => {
  //: 跑着的时候卡在等;用户按停止,宿主收尾时把它作废(ADR 0007 修订 2026-10-08)。不跑的时候「有结论的卡」不轮询 ——
  //: 收尾那一刻不再取一次的话,待决列表里它没了、有结论的那份还停在收尾之前,这一行就既不是卡也没有结论。
  mocks.running = true;
  mocks.streamTimeline = [tool("w1", "edit_note")];
  mocks.cards = [{ id: "card-w1", tool_call_id: "w1", status: "pending" }];
  const { container } = await mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "confirmAllowOnce" })).toBeTruthy());

  mocks.running = false;
  mocks.streamTimeline = [];
  mocks.messages = [
    ...mocks.messages,
    { id: "m9", session_id: "s1", role: "assistant", content: "", error: null, created_at: "2026-10-02T10:00:00",
      payload: { timeline: [tool("w1", "edit_note", "error")] } },
  ];
  mocks.cards = [{ id: "card-w1", tool_call_id: "w1", status: "expired", error: "turn_stopped" }];

  await waitFor(
    () => expect(row(container, "w1")?.querySelector("[data-decision]")?.textContent).toContain("confirmExpiredTurnStopped"),
    { timeout: 6000 },
  );
  expect(screen.queryByRole("button", { name: "confirmAllowOnce" })).toBeNull();
  expect(row(container, "w1")!.textContent).not.toContain("toolFailed");
}, 15_000);
