/** @vitest-environment jsdom */
/**
 * 笔记页的 AI 助手:和剪辑页、画板**同一个面板**(CanvasAgentChat,由 app/pages 交进来),这里只验笔记页给它的那几样 ——
 * 开关与开合记忆、每条消息带上的「这是哪一篇 / 选了哪段」、换篇时跟着换、选中文字后的「问 AI」。
 * 面板本身(会话、发送、确认卡)由 features/agent 下那几份测试守着。
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Editor } from "@tiptap/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { emptyNote, type Note } from "@/api/domains/notes";
import { messages, type MessageKey } from "@/app/messages";
import type { NotesAgentPanelProps } from "./NotesView";

vi.mock("@/app/preferences", () => ({
  usePreferences: () => ({ locale: "zh-CN" }),
  useI18n: () => (key: MessageKey) => messages["zh-CN"][key] ?? key,
}));

type PanelProps = NotesAgentPanelProps;
const panel = { props: null as PanelProps | null };
/** 页面装配层交进来的就是 CanvasAgentChat;这里换成一个记下 props 的替身。 */
function FakePanel(props: PanelProps) {
  panel.props = props;
  return (
    <aside data-testid="notes-agent-panel" data-layout={props.dockedLayout} data-focus-signal={props.focusSignal}>
      {props.contextChips.map((chip) => <span key={chip.id} data-testid="agent-chip">{chip.label}</span>)}
      <button type="button" onClick={props.onClose}>close-agent</button>
    </aside>
  );
}

const notes: Record<string, Note> = {};
const api = vi.hoisted(() => ({
  listNotes: vi.fn(async () => [] as Note[]),
  listNoteTopics: vi.fn(async () => [] as string[]),
  getNote: vi.fn(async (_ws: string, id: string) => notes[id]),
}));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  listNotes: api.listNotes,
  listNoteTopics: api.listNoteTopics,
  getNote: api.getNote,
}));
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

const { NotesView } = await import("./NotesView");

const note = (id: string, title: string, markdown: string): Note =>
  ({ ...emptyNote, id, workspace_id: "ws", title, markdown, revision: 2, save_seq: 2, created_at: "2026-10-01", updated_at: "2026-10-01" });

beforeEach(() => {
  notes.a = note("a", "周报", "周一和**剪辑组**对了节奏。\n\n周二写了脚本。");
  notes.b = note("b", "拍摄清单", "一号机位。");
  panel.props = null;
});
afterEach(() => { cleanup(); localStorage.clear(); window.location.hash = ""; vi.clearAllMocks(); });

function mount() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NotesView workspace={{ id: "ws", role: "editor" } as never} AgentPanel={FakePanel} />
    </QueryClientProvider>,
  );
}

/** 页面里那个真的笔记编辑器(TipTap 把自己挂在 DOM 上)。 */
async function noteEditor(): Promise<Editor> {
  await waitFor(() => expect(document.querySelector(".note-prose")).not.toBeNull());
  return (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;
}

function select(editor: Editor, from: string, to: string) {
  let start = -1;
  let end = -1;
  editor.state.doc.descendants((node, pos) => {
    if (!node.isText) return;
    const a = node.text!.indexOf(from);
    if (start < 0 && a >= 0) start = pos + a;
    const b = node.text!.indexOf(to);
    if (b >= 0) end = pos + b + to.length;
  });
  act(() => { editor.commands.setTextSelection({ from: start, to: end }); });
}

const context = () => panel.props!.contextLine();

it("顶栏有 AI 助手开关:打开是停靠的同一个面板,开合记在本地,从面板关掉不留空容器", async () => {
  window.location.hash = "#/notes?note=a";
  const first = mount();
  const toggle = await screen.findByRole("button", { name: "AI 助手" });
  expect(screen.queryByTestId("notes-agent-panel")).toBeNull();

  fireEvent.click(toggle);

  expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("notes-agent-panel")).toHaveAttribute("data-layout", "inline");
  expect(screen.getByTestId("notes-agent-slot")).toHaveStyle({ flex: "0 0 400px" });
  //: 列表那条拖边之外,助手左缘也有一条(宽度可拖)。
  expect(screen.getAllByRole("separator")).toHaveLength(2);
  expect(localStorage.getItem("mosael:tab:notes-agent")).toBe("on");

  //: 切走再回来:还开着。
  first.unmount();
  mount();
  expect(await screen.findByTestId("notes-agent-panel")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "close-agent" }));
  expect(screen.queryByTestId("notes-agent-slot")).toBeNull();
  expect(localStorage.getItem("mosael:tab:notes-agent")).toBe("off");
});

it("每条消息带上当前这篇:标题、id、正文;选中一段后带上它的正文原文", async () => {
  localStorage.setItem("mosael:tab:notes-agent", "on");
  window.location.hash = "#/notes?note=a";
  mount();
  const editor = await noteEditor();
  await screen.findByTestId("notes-agent-panel");

  expect(context()).toContain("「周报」");
  expect(context()).toContain("note_id=a");
  expect(context()).toContain("周二写了脚本。");
  expect(context()).not.toContain("用户选中了");

  select(editor, "周一", "节奏");

  //: 选区停下来之后才报(防抖),报了之后小条出现、上下文里是带着 ** 的正文原文。
  await waitFor(() => expect(context()).toContain("用户选中了这一段"));
  expect(context()).toContain("周一和**剪辑组**对了节奏");
  //: 小条上给人看的去掉了 Markdown 记号;发出去的仍是原文。
  expect(screen.getByTestId("agent-chip")).toHaveTextContent("周一和剪辑组对了节奏");
  //: 这条消息带着的摘录(气泡里那一行):哪篇、标题、正文原文、位置。
  expect(panel.props!.messageQuote).toMatchObject({ kind: "note", note_id: "a", title: "周报", text: "周一和**剪辑组**对了节奏" });

  //: 点掉小条:这一段不再跟着发。
  act(() => panel.props!.contextChips![0].onRemove());
  expect(context()).not.toContain("用户选中了");
  expect(screen.queryByTestId("agent-chip")).toBeNull();
  expect(panel.props!.messageQuote).toBeNull();
});

it("换一篇笔记:上下文跟着换成那一篇,上一篇的选区不带过去", async () => {
  localStorage.setItem("mosael:tab:notes-agent", "on");
  window.location.hash = "#/notes?note=a";
  mount();
  const editor = await noteEditor();
  select(editor, "周二", "脚本");
  await waitFor(() => expect(context()).toContain("周二写了脚本"));

  act(() => {
    window.location.hash = "#/notes?note=b";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });

  await waitFor(() => expect(context()).toContain("「拍摄清单」"));
  expect(context()).toContain("note_id=b");
  expect(context()).not.toContain("周报");
  expect(context()).not.toContain("用户选中了");
  expect(screen.queryByTestId("agent-chip")).toBeNull();
});

it("选中文字后浮出「问 AI」:点它打开助手、带上这一段、把光标交给输入框", async () => {
  window.location.hash = "#/notes?note=a";
  mount();
  const editor = await noteEditor();
  expect(screen.queryByRole("button", { name: "问 AI" })).toBeNull();

  act(() => { editor.commands.focus(); });
  select(editor, "周二", "脚本");
  const ask = await screen.findByRole("button", { name: "问 AI" });

  fireEvent.click(ask);

  const opened = await screen.findByTestId("notes-agent-panel");
  expect(opened).toHaveAttribute("data-focus-signal", "1");
  expect(screen.getByTestId("agent-chip")).toHaveTextContent("周二写了脚本");
  expect(context()).toContain("用户选中了这一段");
  expect(localStorage.getItem("mosael:tab:notes-agent")).toBe("on");
});

/** 把编辑器聚焦并选中一段(工具条只在编辑器有焦点时出现)。 */
function focusSelect(editor: Editor, from: string, to: string) {
  act(() => { editor.commands.focus(); });
  select(editor, from, to);
}

it("选区工具条的 AI 动作:打开助手、钉住这段、投递一条带指令的消息;改写类要求用 edit_note 落回", async () => {
  window.location.hash = "#/notes?note=a";
  mount();
  const editor = await noteEditor();
  focusSelect(editor, "周二", "脚本");
  fireEvent.click(await screen.findByRole("button", { name: "AI 动作" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: /润色/ }));

  await screen.findByTestId("notes-agent-panel");
  const outbox = panel.props!.outbox!;
  expect(outbox.text).toBe("润色选中的这段");
  expect(outbox.context).toContain("edit_note");
  expect(outbox.context).toContain("replace");
  expect(screen.getByTestId("agent-chip")).toHaveTextContent("周二写了脚本");
  expect(context()).toContain("周二写了脚本");

  //: 面板接走之后页面清掉,重新打开面板不会再发一次。
  act(() => panel.props!.onOutboxTaken!());
  expect(panel.props!.outbox).toBeNull();
});

it("翻译:中文选区译成英文;总结只回答、不改笔记", async () => {
  window.location.hash = "#/notes?note=a";
  mount();
  const editor = await noteEditor();
  focusSelect(editor, "周二", "脚本");
  fireEvent.click(await screen.findByRole("button", { name: "AI 动作" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: /翻译/ }));
  await screen.findByTestId("notes-agent-panel");
  expect(panel.props!.outbox!.text).toBe("把选中的这段翻译成英文");
  act(() => panel.props!.onOutboxTaken!());

  focusSelect(editor, "周二", "脚本");
  fireEvent.click(await screen.findByRole("button", { name: "AI 动作" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: /总结/ }));
  expect(panel.props!.outbox!.context).toContain("不要改笔记");
});

it("引用到对话:只把这段挂成小条,不发、不抢输入框焦点;选区变了小条还在,发出去之后才放下", async () => {
  window.location.hash = "#/notes?note=a";
  mount();
  const editor = await noteEditor();
  focusSelect(editor, "周二", "脚本");
  fireEvent.click(await screen.findByRole("button", { name: "引用到对话" }));

  await screen.findByTestId("notes-agent-panel");
  expect(panel.props!.outbox).toBeNull();
  expect(panel.props!.focusSignal).toBe(0);
  expect(screen.getByTestId("agent-chip")).toHaveTextContent("周二写了脚本");

  act(() => { editor.commands.setTextSelection(2); });
  await new Promise((resolve) => setTimeout(resolve, 250));
  expect(screen.getByTestId("agent-chip")).toHaveTextContent("周二写了脚本");

  act(() => panel.props!.onSent!());
  await waitFor(() => expect(screen.queryByTestId("agent-chip")).toBeNull());
})
