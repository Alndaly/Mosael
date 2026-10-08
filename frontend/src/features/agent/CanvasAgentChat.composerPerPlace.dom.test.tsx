/** @vitest-environment jsdom */

/**
 * 输入框里没发出去的东西按地方分(ADR 0044「每一处各接各的」,智能体那一路 AGENT-9)。
 *
 * 现场:笔记 A 的面板里打了「把这篇笔记的第一段删掉」没发,点开笔记 B —— 面板换成 B 的新对话,输入框里还是那句话;
 * 页面上下文在发送那一刻读的是 B,发出去就是对 B。这里断言**输入框里画出来的字**和**挂着的引用**跟着地方走、回来还在,
 * 发出去的那一条用的是这一处的字。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const sent = vi.hoisted(() => [] as [string, { content: string; place?: unknown }][]);

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  isNotFound: () => false,
  listAgentSessions: vi.fn(async () => []),
  getAgentSession: vi.fn(async (id: string) => ({ id, workspace_id: "w1", title: "t", is_mine: true, status: "idle", home_kind: "note", home_id: "b" })),
  createAgentSession: vi.fn(async (body: { home: { kind: string; id: string } }) => ({
    id: `s-${body.home.id}`, workspace_id: "w1", title: "新对话", is_mine: true, status: "idle", home_kind: body.home.kind, home_id: body.home.id,
  })),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  listAgentMessages: vi.fn(async () => []),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(async (id: string, body: { content: string }) => {
    sent.push([id, body]);
    return { id: "m1", session_id: id, role: "user", content: body.content, payload: {}, error: null, created_at: "2026-10-08T00:00:00" };
  }),
  api: vi.fn(async () => ({})),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
//: 引用的笔记:一份有状态的假 hook(和真的一样只认 clear / selected / restore),「加一篇」由触发键做。
vi.mock("@/features/notes/useNoteAttachments", async () => {
  const ReactModule = await import("react");
  return {
    useNoteAttachments: () => {
      const [selected, setSelected] = ReactModule.useState<{ id: string; title: string }[]>([]);
      return {
        hasNotes: selected.length > 0, context: "", summary: selected.map((n) => `@${n.title}`).join(" "), chips: [],
        dialog: <span data-testid="attached-notes">{selected.map((n) => n.title).join(",")}</span>,
        trigger: <button type="button" onClick={() => setSelected((old) => [...old, { id: "n9", title: "参考笔记" }])}>attach-note</button>,
        clear: () => setSelected([]), selected, restore: (notes: { id: string; title: string }[]) => setSelected(notes),
      };
    },
  };
});
vi.mock("@/features/agent/composerAttachments", () => ({
  MAX_CONTEXT_CHARS: 4000,
  MAX_MESSAGE_CHARS: 8000,
  textAttachmentBlock: () => "",
  useComposerAttachments: () => ({
    isEmpty: true, files: [], media: [], chips: [], uploading: false, previewModal: null,
    onPaste() {}, drop: { handlers: {}, overlay: null }, accept() {}, clear() {}, restore() {},
  }),
}));
//: 输入框换成一个受控的 textarea:文档就是 `{ text }`。
vi.mock("@/features/agent/ChatComposer", () => ({
  ChatComposer: ({ value, onChange, onSubmit }: { value: { text?: string }; onChange: (doc: { type: string; text: string }) => void; onSubmit: () => void }) => (
    <textarea
      aria-label="composer"
      value={value.text ?? ""}
      onChange={(event) => onChange({ type: "doc", text: event.target.value })}
      onKeyDown={(event) => event.key === "Enter" && onSubmit()}
    />
  ),
  appendText: (doc: unknown) => doc,
  collectReferences: () => [],
  documentText: (doc: { text?: string }) => doc.text ?? "",
  emptyDocument: { type: "doc", text: "" },
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
import type { AgentPlace } from "./places";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

afterEach(() => {
  sent.length = 0;
  window.sessionStorage.clear();
});

const NOTE_A: AgentPlace = { kind: "note", id: "a" };
const NOTE_B: AgentPlace = { kind: "note", id: "b" };

function Panel({ place }: { place: AgentPlace }) {
  return (
    <CanvasAgentChat
      contextLine={() => `笔记 ${place.id} 的正文`}
      emptyHint="hint"
      placeholder="说点什么"
      rectKey="test"
      workspaceId="w1"
      place={place}
      mode="docked"
    />
  );
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <Panel place={NOTE_A} />
    </QueryClientProvider>,
  );
  const show = (place: AgentPlace) =>
    view.rerender(
      <QueryClientProvider client={qc}>
        <Panel place={place} />
      </QueryClientProvider>,
    );
  return { show };
}

const box = () => screen.getByLabelText("composer") as HTMLTextAreaElement;
const notes = () => screen.getByTestId("attached-notes").textContent;

it("在 A 打了一半的话、挂的引用,换到 B 不跟着走;回到 A 还在", async () => {
  const { show } = mount();
  fireEvent.change(box(), { target: { value: "把这篇笔记的第一段删掉" } });
  fireEvent.click(screen.getByRole("button", { name: "attach-note" }));
  expect(notes()).toBe("参考笔记");

  act(() => show(NOTE_B));
  await waitFor(() => expect(box().value).toBe(""));
  expect(notes(), "A 挂的引用跟到了 B").toBe("");
  fireEvent.change(box(), { target: { value: "B 的问题" } });

  act(() => show(NOTE_A));
  await waitFor(() => expect(box().value).toBe("把这篇笔记的第一段删掉"));
  expect(notes()).toBe("参考笔记");

  act(() => show(NOTE_B));
  await waitFor(() => expect(box().value).toBe("B 的问题"));
});

it("发出去的是这一处的字;发完这一处清空,别处的不受影响", async () => {
  const { show } = mount();
  fireEvent.change(box(), { target: { value: "A 还没想好" } });
  act(() => show(NOTE_B));
  await waitFor(() => expect(box().value).toBe(""));
  fireEvent.change(box(), { target: { value: "总结一下这篇" } });
  fireEvent.keyDown(box(), { key: "Enter" });
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0][1].content).toBe("总结一下这篇");
  expect(sent[0][1].place).toEqual(NOTE_B);
  await waitFor(() => expect(box().value).toBe(""));

  act(() => show(NOTE_A));
  await waitFor(() => expect(box().value).toBe("A 还没想好"));
  act(() => show(NOTE_B));
  await waitFor(() => expect(box().value).toBe(""));
});

it("同一个窗口里重新加载页面,这一处没发出去的字还在(只记这一次运行,和每处的选择一样)", async () => {
  const first = mount();
  fireEvent.change(box(), { target: { value: "写到一半" } });
  first.show(NOTE_B);
  // 重新挂一次(相当于重新加载页面):A 的那半句从 sessionStorage 里回来。
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <div data-testid="again"><Panel place={NOTE_A} /></div>
    </QueryClientProvider>,
  );
  const again = screen.getByTestId("again").querySelector("textarea") as HTMLTextAreaElement;
  expect(again.value).toBe("写到一半");
});
