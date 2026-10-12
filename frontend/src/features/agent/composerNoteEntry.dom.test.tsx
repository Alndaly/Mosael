/** @vitest-environment jsdom */

/**
 * 输入框下面那一行**不再有「引用笔记」那个入口**(用户:「输入框下方这个引用笔记的这个交互入口可以去掉了」)。
 *
 * 为什么去掉:同一件事有两个入口,而 `@` 那个更好 —— 引用是正文里的原子节点(整条选中、整条删掉),
 * 而这条按钮是挂在消息外面的附件。留着它,用户得先想清楚"这次该按哪个"。**能力没有被删掉**:引用笔记
 * 仍旧从 `@` 菜单进(见 mentionTruncation.dom.test.tsx 里那条"选中一条笔记落成 note 引用")。
 *
 * 这条用例是**守卫**:按无障碍名判(不是按 class),所以从那以后谁再往这一行加回一个「引用笔记」,
 * 或者把 `@` 那份能力挪走,它都会红。旁边那几样(附件、发送)照着断言,免得"整行都没了"也算过。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  isNotFound: () => false,
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", home_kind: "note", home_id: "n1", home_name: "", home_state: "ok", title: "对话", is_mine: true }]),
  getAgentSession: vi.fn(async (id: string) => ({ id, workspace_id: "w1", home_kind: "note", home_id: "n1", home_name: "", home_state: "ok", title: "对话", status: "idle", is_mine: true })),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  listAgentMessages: vi.fn(async () => []),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
  api: vi.fn(async () => ({})),
}));
//: 真给 `usePreferences`(不只是 useI18n):笔记那份文案表(`notes/strings.ts`)按它取中英 —— 这一行
//: 要是又长出一个「引用笔记」,读到的就是"引用笔记"这四个字,而不是一个崩掉的替身。
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", theme: "system", setLocale: () => {}, setTheme: () => {} }),
}));
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_MESSAGE_CHARS: 8000,
  MAX_CONTEXT_CHARS: 4000,
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
  emptyDocument: { type: "doc", content: [{ type: "paragraph" }] },
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
  window.sessionStorage.clear();
});

it("这一行里没有「引用笔记」入口了,而附件、发送照旧在", async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CanvasAgentChat
        contextLine={() => "这一篇笔记的正文"}
        emptyHint="hint"
        placeholder="说点什么"
        rectKey="test"
        workspaceId="w1"
        place={{ kind: "note", id: "n1" }}
        mode="docked"
      />
    </QueryClientProvider>,
  );
  await screen.findByLabelText("composer");
  await waitFor(() => expect(screen.queryByRole("button", { name: "wfAgentAttach" })).toBeTruthy());
  //: 中英两种写法都判:文案表按界面语言取,只判中文的话把界面切成英文就漏了。
  expect(screen.queryByRole("button", { name: /引用笔记|Reference a note/ }), "「引用笔记」那本书又回来了").toBeNull();
  //: 一行里也不该只剩下发送键(那就成了"整行都没了"也算过)。
  expect(screen.queryByRole("button", { name: "wfAgentAttach" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /chatSend|wfAgentSend/ })).toBeTruthy();
});
