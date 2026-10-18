/** @vitest-environment jsdom */

/**
 * 「智能体环境」的头部不许被下面的内容压住,也不许因为换会话把整列重建。
 *
 * 现场(维护者截图):面板最上面那行「智能体环境」被一层内容盖住,看起来像头部没了。它不是被别的
 * 东西盖上来,而是**自己塌成了 0** —— 头部那一行的 `height` 来自工具栏量出来的 `toolbarHeight`,
 * 高度一旦是 0,就只剩 `border-b` 那 1px,标题字正常溢出画在那一行里,而紧跟着的滚动内容区从
 * 同一个 y 开始画,后画的那一层就把字盖住了(`elementFromPoint` 落在标题上返回的是内容区)。
 *
 * 触发条件是**整列被重建**:会话从草稿变成一条时,`SessionDecisions` 此前从裸 fragment 换成
 * Provider —— 旧工具栏离开文档,ResizeObserver 还会对离开文档的元素报一次 0 尺寸;观察器把这次 0
 * 写进 `toolbarHeight`,而新的那根工具栏从此没人观察。测量那一侧已经改成 ref 回调(节点一换就重新
 * 观察、0 一律不写),但**根因是重建本身** —— 这一列不该重建。
 *
 * 这条测试同时钉两件事:
 *   1. 草稿 → 选中一段会话,**工具栏还是同一个 DOM 节点**(整列没有重建);
 *   2. 同一根工具栏量出来的高度照旧是面板头部的高度,工具栏变高时头部跟着变。
 * DOM 测不了像素,但"头部高度塌成 0"正是覆盖现象在 DOM 里的那一半:头部一旦是 0,内容必然画在标题上。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { adoptAgentSession, startAgentDraft } from "@/features/agent/sessionSelection";
import { STUDIO_PLACE } from "@/features/agent/places";

vi.mock("@/api/client", () => ({
  isNotFound: () => false,
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  api: vi.fn(async () => ({})),
  agentManifest: vi.fn(async () => ({ version: "1" })),
  listAgentTools: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => [
    { id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "长对话", is_mine: true },
  ]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({
    id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok",
    title: "长对话", status: "idle", is_mine: true,
  })),
  listAgentMessages: vi.fn(async () => [
    { id: "m1", session_id: "s1", role: "user", content: "第一句", payload: {}, error: null, created_at: "2026-10-18T00:00:00" },
    { id: "m2", session_id: "s1", role: "assistant", content: "第一句的回答", payload: { timeline: [{ type: "text", text: "第一句的回答" }] }, error: null, created_at: "2026-10-18T00:00:01" },
  ]),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  getAgentVoice: vi.fn(async () => ({ speak_early: true })),
  listAgentQuestions: vi.fn(async () => []),
  answerAgentQuestion: vi.fn(),
  dismissAgentQuestion: vi.fn(),
  listConfirmations: vi.fn(async () => []),
  approveConfirmation: vi.fn(),
  rejectConfirmation: vi.fn(),
  addSessionAllowance: vi.fn(),
  sendAgentMessage: vi.fn(),
  fetchJobKinds: vi.fn(async () => ({
    kinds: [], fallback: { kind: "", label: "任务", announce: "always", affects: [], view: null, record_field: null },
  })),
  topLevelJobsQuery: () => ({ queryKey: ["jobs", "w1", "top-level"], queryFn: async () => [] }),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  listJobEvents: vi.fn(async () => []),
  listJobChildren: vi.fn(async () => []),
  regenerateAssetProxy: vi.fn(),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  resumeQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/api/domains/sessions", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  streamAgentTurn: vi.fn(async () => new Response("data: {\"text\":\"\",\"done\":true,\"timeline\":[]}\n\n")),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_MESSAGE_CHARS: 8000,
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true, files: [], media: [], chips: [], uploading: false, previewModal: null,
    onPaste() {}, drop: { handlers: {}, overlay: null }, accept() {}, clear() {},
  }),
}));
vi.mock("@/features/ai-studio/SessionList", () => ({ SessionList: () => null }));
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => null }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => null }));
vi.mock("@/features/agent/effectiveModel", () => ({ useEffectiveChatModel: () => ({ model: "m" }) }));
vi.mock("@/features/agent/QueuedMessages", () => ({ QueuedMessages: () => null }));
vi.mock("@/features/agent/trace/TraceView", () => ({ TraceView: () => null, TraceStatsBar: () => null }));
vi.mock("@/features/agent/trace/traceModel", () => ({ buildTurns: () => [] }));

import { ChatWorkspace } from "./ChatWorkspace";

/** 工具栏量出来的高度。`0` 只该出现在"它已经离开文档"的时候 —— 浏览器就是这么报的。 */
const metrics = { toolbar: 56 };

/**
 * ResizeObserver 的替身:记下观察了谁,**只对还观察着的目标**回调(断开之后不再说话,和真的同语义)。
 * `getBoundingClientRect` 也替身(jsdom 没有排版):工具栏在文档里报 `metrics.toolbar`,离开文档报 0。
 */
class FakeResizeObserver {
  static all: FakeResizeObserver[] = [];
  private targets = new Set<Element>();
  constructor(private readonly callback: () => void) {
    FakeResizeObserver.all.push(this);
  }
  observe(target: Element) { this.targets.add(target); }
  unobserve(target: Element) { this.targets.delete(target); }
  disconnect() { this.targets.clear(); }
  /** 浏览器报尺寸变化(离开文档的那一次报 0)。 */
  private fire() { if (this.targets.size > 0) this.callback(); }
  static fireAll() { for (const observer of FakeResizeObserver.all) observer.fire(); }
}

const rect = (height: number): DOMRect => ({
  x: 0, y: 0, top: 0, left: 0, right: 0, bottom: height, width: 0, height,
  toJSON: () => ({}),
}) as DOMRect;

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  metrics.toolbar = 56;
  FakeResizeObserver.all = [];
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    //: 只有工具栏(唯一带 min-h-14 的那一条)有真高度;别的东西这里量到 0 就够了。
    const toolbar = this instanceof HTMLElement && this.className.includes("min-h-14");
    return rect(toolbar && this.isConnected ? metrics.toolbar : 0);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChatWorkspace workspace={{ id: "w1", name: "工作区" } as never} />
    </QueryClientProvider>,
  );
  //: 草稿(还没有会话)是维护者每天进来的样子。
  await screen.findByText("studioChatStart");
}

it("会话从草稿变成一条时整列不重建,面板头部照旧跟着工具栏,内容不会压上来", async () => {
  startAgentDraft("w1", STUDIO_PLACE);
  await mount();

  fireEvent.click(screen.getByRole("button", { name: "agentInspectorTitle" }));
  const aside = await screen.findByRole("complementary", { name: "agentInspectorTitle" });
  const header = aside.firstElementChild as HTMLElement;
  const content = aside.children[1] as HTMLElement;

  //: 结构这一半:头部是面板的第一行、自己不缩(`shrink-0`);能滚的是它后面那一层。
  expect(aside.children[0]).toBe(header);
  expect(header.className).toContain("shrink-0");
  expect(content.className).toContain("overflow-y-auto");
  expect(content.className).toContain("min-h-0");
  expect(header.style.height, "面板头部没跟着工具栏的高度").toBe("56px");

  const toolbarBefore = document.querySelector('section div[class*="min-h-14"]');
  expect(toolbarBefore, "没找到工具栏").not.toBeNull();

  //: 草稿 → 选中一段对话。`SessionDecisions` 必须**始终**有一个 Provider 在树上;此前草稿态是
  //: 裸 fragment,一换会话整列被重建 —— 这就是"头部塌成 1px"的触发条件。
  act(() => { adoptAgentSession("w1", STUDIO_PLACE, "s1"); });
  await screen.findByText("第一句");
  const toolbarAfter = document.querySelector('section div[class*="min-h-14"]');
  expect(toolbarAfter, "工具栏换了 DOM 节点:整列被重建了").toBe(toolbarBefore);
  expect(toolbarAfter!.isConnected, "整列重建把工具栏从文档里摘掉了").toBe(true);

  //: 浏览器报尺寸变化(比如真实环境里离开文档的旧节点那次 0)—— 不许变成面板头部的高度。
  act(() => { FakeResizeObserver.fireAll(); });
  expect(
    header.style.height,
    "0 高度被当成了面板头部的高度:头部会塌成 1px,下面的卡片就压在「智能体环境」上",
  ).toBe("56px");

  //: 观察器得挂在工具栏上:工具栏变高(窄窗口换行),头部跟着变。
  metrics.toolbar = 84;
  act(() => { FakeResizeObserver.fireAll(); });
  expect(header.style.height, "工具栏的尺寸变化没人跟了").toBe("84px");
});
