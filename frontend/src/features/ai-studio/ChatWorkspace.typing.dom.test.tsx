/** @vitest-environment jsdom */

/**
 * 打字不重画已有的气泡(前端架构分析 FA-04)。
 *
 * 现场:一段三百条的对话里打字,4× 降频下帧间隔 p95 一秒多 —— 草稿是对话页顶层的 state,每敲一个字整页重渲,
 * 三百个气泡连同 Markdown、代码高亮、工具行全部再算一遍。现在草稿放在面板的渲染状态之外(composerDraft),
 * 只有输入框和发送键订阅它;气泡是 memo 的,对话页为别的事重渲(开右栏、运行计时、轮询)也不重画它们。
 *
 * 这里数的是气泡里那两样最重的东西各画了几次:用户消息的正文、助手那一轮的内容。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { AGENT_DRAFT_EVENT } from "@/features/agent/currentAgentSession";
import { adoptAgentSession } from "@/features/agent/sessionSelection";
import { emitOpenEvent } from "@/lib/deepLink";

const renders = vi.hoisted(() => ({ user: 0, assistant: 0 }));
const sent = vi.hoisted(() => [] as { content: string }[]);

vi.mock("@/api/client", () => ({
  isNotFound: () => false,
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  api: vi.fn(async () => ({})),
  agentManifest: vi.fn(async () => ({ version: "1" })),
  listAgentTools: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "长对话", is_mine: true }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", home_kind: "studio", home_id: "", home_name: "", home_state: "ok", title: "长对话", status: "idle", is_mine: true })),
  listAgentMessages: vi.fn(async () => [
    { id: "m1", session_id: "s1", role: "user", content: "第一句", payload: {}, error: null, created_at: "2026-10-08T00:00:00" },
    { id: "m2", session_id: "s1", role: "assistant", content: "第一句的回答", payload: { timeline: [{ type: "text", text: "第一句的回答" }] }, error: null, created_at: "2026-10-08T00:00:01" },
    { id: "m3", session_id: "s1", role: "user", content: "第二句", payload: {}, error: null, created_at: "2026-10-08T00:00:02" },
  ]),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(async (id: string, body: { content: string }) => {
    sent.push(body);
    return { id: "m4", session_id: id, role: "user", content: body.content, payload: {}, error: null, created_at: "2026-10-08T00:00:03" };
  }),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/api/domains/sessions", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  streamAgentTurn: vi.fn(async () => new Response("data: {\"text\":\"\",\"done\":true,\"timeline\":[]}\n\n")),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear() {} }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_MESSAGE_CHARS: 8000,
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true, files: [], media: [], chips: [], uploading: false, previewModal: null,
    onPaste() {}, drop: { handlers: {}, overlay: null }, accept() {}, clear() {},
  }),
}));
//: 输入框换成一个受控的 textarea:打的字记成 `{ text }`;别处填进来的是真的段落文档,按段落拼回字。
vi.mock("@/features/agent/ChatComposer", () => {
  type Doc = { text?: string; content?: { content?: { text?: string }[] }[] };
  const documentText = (doc: Doc) => doc.text ?? (doc.content ?? []).map((p) => (p.content ?? []).map((n) => n.text ?? "").join("")).join("\n");
  return {
    ChatComposer: ({ value, onChange }: { value: Doc; onChange: (doc: { type: string; text: string }) => void }) => (
      <textarea aria-label="composer" value={documentText(value)} onChange={(event) => onChange({ type: "doc", text: event.target.value })} />
    ),
    appendText: (doc: unknown) => doc,
    collectReferences: () => [],
    documentText,
    emptyDocument: { type: "doc", text: "" },
  };
});
//: 气泡里最重的两样换成数次数的替身,其余照真的。
vi.mock("@/features/agent/userMessage", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  UserMessageContent: ({ content }: { content: string }) => {
    renders.user += 1;
    return <span>{content}</span>;
  },
}));
vi.mock("@/features/agent/ToolCalls", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  AgentTurnContent: ({ timeline }: { timeline?: { text?: string }[] }) => {
    renders.assistant += 1;
    return <span>{(timeline ?? []).map((item) => item.text).join("")}</span>;
  },
}));
vi.mock("@/features/agent/messageUsage", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  MessageUsageFooter: () => null,
  MessageFooter: () => null,
}));
vi.mock("@/features/ai-studio/SessionList", () => ({ SessionList: () => null }));
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => null }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => null }));
vi.mock("@/features/agent/effectiveModel", () => ({ useEffectiveChatModel: () => ({ model: "m" }) }));
vi.mock("@/features/agent/PendingDecisions", () => ({
  SessionDecisions: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PendingDecisions: () => null,
  JumpToLatestOrDecision: () => null,
}));
vi.mock("@/features/agent/QueuedMessages", () => ({ QueuedMessages: () => null }));
vi.mock("@/features/agent/trace/TraceView", () => ({ TraceView: () => null, TraceStatsBar: () => null }));
vi.mock("@/features/agent/trace/traceModel", () => ({ buildTurns: () => [] }));

import { ChatWorkspace } from "./ChatWorkspace";

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  adoptAgentSession("w1", { kind: "studio", id: "" }, "s1");
  renders.user = 0;
  renders.assistant = 0;
  sent.length = 0;
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChatWorkspace workspace={{ id: "w1", name: "工作区" } as never} />
    </QueryClientProvider>,
  );
  await screen.findByText("第二句");
  await screen.findByText("第一句的回答");
}

const box = () => screen.getByLabelText("composer") as HTMLTextAreaElement;

it("打字不重画已有的气泡;发送键跟着框里空不空走,发出去的是打的那句,发完清空", async () => {
  await mount();
  const settled = { ...renders };
  expect(screen.getByRole("button", { name: "chatSend" })).toBeDisabled();

  for (const text of ["帮", "帮我", "帮我看", "帮我看看", "帮我看看第三个镜头"]) {
    fireEvent.change(box(), { target: { value: text } });
  }
  expect(box().value).toBe("帮我看看第三个镜头");
  expect(renders.user - settled.user, "打字时用户气泡被重画了").toBe(0);
  expect(renders.assistant - settled.assistant, "打字时助手气泡被重画了").toBe(0);
  expect(screen.getByRole("button", { name: "chatSend" })).toBeEnabled();

  fireEvent.click(screen.getByRole("button", { name: "chatSend" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0].content).toBe("帮我看看第三个镜头");
  await waitFor(() => expect(box().value).toBe(""));
});

it("对话页为别的事重渲(开右侧的智能体环境)也不重画气泡", async () => {
  await mount();
  const settled = { ...renders };
  fireEvent.click(screen.getByRole("button", { name: "agentInspectorTitle" }));
  await screen.findByRole("complementary", { name: "agentInspectorTitle" });
  expect(renders.user - settled.user, "开右栏时用户气泡被重画了").toBe(0);
  expect(renders.assistant - settled.assistant, "开右栏时助手气泡被重画了").toBe(0);
});

it("别处带着一段话来(内嵌浏览器「交给智能体」):填进输入框、一行一段,不替他发,也不重画气泡", async () => {
  await mount();
  const settled = { ...renders };
  act(() => emitOpenEvent(AGENT_DRAFT_EVENT, "看看这个页面\nhttps://example.test/a"));
  await waitFor(() => expect(box().value).toBe("看看这个页面\nhttps://example.test/a"));
  expect(sent).toHaveLength(0);
  expect(screen.getByRole("button", { name: "chatSend" })).toBeEnabled();
  expect(renders.user - settled.user).toBe(0);
  expect(renders.assistant - settled.assistant).toBe(0);
});
