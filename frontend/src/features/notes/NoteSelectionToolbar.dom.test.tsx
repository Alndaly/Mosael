/** @vitest-environment jsdom */
/**
 * 选中文字后浮出的选区工具条:格式、AI 快捷动作、问 AI、复制、转列表 / 待办、引用到对话、朗读、存到笔记。
 *
 * 用真的笔记编辑器验:工具条出不出来、摆在哪、键盘走不走得通、每个格式命令是不是作用在选区上、
 * AI 动作和引用交出去的是不是这段选区、朗读走的是不是免费的 Edge 引擎(不建素材)、窄屏收成「更多」。
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Editor } from "@tiptap/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ usePreferences: () => ({ locale: "zh-CN" }), useI18n: () => (key: string) => key }));
const speech = vi.hoisted(() => ({
  fetchVoicePreview: vi.fn(async () => new Blob(["audio"], { type: "audio/mpeg" })),
  readWithAgentVoice: vi.fn(async () => new Blob(["audio"], { type: "audio/mpeg" })),
  synthesizeWithEngine: vi.fn(async () => ({ id: "job-1" })),
  //: 设置「语音对话」里选的那把嗓子;默认没选过。
  agentVoice: { engine: "", engine_voice: "", engine_voice_resource: "", engine_model: "", speed: 1, enabled: false },
}));
vi.mock("@/api/domains/speech", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/speech")>()),
  fetchVoicePreview: speech.fetchVoicePreview,
  readWithAgentVoice: speech.readWithAgentVoice,
  synthesizeWithEngine: speech.synthesizeWithEngine,
  getAgentVoice: vi.fn(async () => speech.agentVoice),
}));
vi.mock("@/api/domains/boards", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/boards")>()),
  listBoards: vi.fn(async () => []),
}));
vi.mock("@/api/domains/notes", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/domains/notes")>()),
  listNotes: vi.fn(async () => []),
}));
vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} });

const { NoteEditor } = await import("./NoteEditor");

const handlers = { onAskAi: vi.fn(), onAiAction: vi.fn(), onQuote: vi.fn() };
const writeText = vi.fn(async () => {});

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText } });
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:audio", revokeObjectURL: () => {} }));
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    queueMicrotask(() => this.dispatchEvent(new Event("ended")));
    return Promise.resolve();
  });
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.restoreAllMocks(); });

function mount(markdown = "周一和剪辑组对了节奏。\n\n周二写了脚本,还加了链接文字。") {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NoteEditor markdown={markdown} onChange={() => {}} onReference={() => {}} workspaceId="ws" noteId="n1" {...handlers}
        saveSource={{ kind: "note", id: "n1", label: "周报", quote: "", revision: 2 }} />
    </QueryClientProvider>,
  );
}

async function editor(): Promise<Editor> {
  await waitFor(() => expect(document.querySelector(".note-prose")).not.toBeNull());
  return (document.querySelector(".note-prose") as unknown as { editor: Editor }).editor;
}

function select(instance: Editor, text: string) {
  let from = -1;
  instance.state.doc.descendants((node, pos) => {
    if (from < 0 && node.isText && node.text!.includes(text)) from = pos + node.text!.indexOf(text);
  });
  act(() => { instance.chain().focus().setTextSelection({ from, to: from + text.length }).run(); });
}

const toolbar = () => screen.queryByRole("toolbar", { name: "选区工具" });
//: 只在选区工具条里找 —— 页面顶上的格式工具栏也有一颗「粗体」。
const button = (name: string) => within(toolbar()!).getByRole("button", { name });

it("有选区、编辑器有焦点时才出现;选区收成光标就收起", async () => {
  mount();
  const instance = await editor();
  expect(toolbar()).toBeNull();
  select(instance, "剪辑组");
  expect(await screen.findByRole("toolbar", { name: "选区工具" })).toBeInTheDocument();
  act(() => { instance.commands.setTextSelection(3); });
  await waitFor(() => expect(toolbar()).toBeNull());
});

it("摆在选区上方;贴着窗口顶部时翻到下方,并收进窗口左右边", async () => {
  mount();
  const instance = await editor();
  const coords = vi.spyOn(instance.view, "coordsAtPos").mockReturnValue({ top: 300, bottom: 320, left: 2000, right: 2060 });
  select(instance, "剪辑组");
  const bar = await screen.findByRole("toolbar", { name: "选区工具" });
  expect(bar.getAttribute("data-placement")).toBe("above");
  expect(parseFloat(bar.style.top)).toBeLessThan(300);
  //: 选区在窗口右边外面:收进来,不伸出窗口。
  expect(parseFloat(bar.style.left)).toBeLessThanOrEqual(1280);

  coords.mockReturnValue({ top: 30, bottom: 50, left: 100, right: 160 });
  act(() => { window.dispatchEvent(new Event("resize")); });
  await waitFor(() => expect(bar.getAttribute("data-placement")).toBe("below"));
  //: 翻到下方时在选区底边之下 —— 不盖住选中的字。
  expect(parseFloat(bar.style.top)).toBeGreaterThanOrEqual(50);
});

it("键盘:Tab 进入工具条,方向键在按钮间移动,Esc 收起并回到正文", async () => {
  mount();
  const instance = await editor();
  select(instance, "剪辑组");
  await screen.findByRole("toolbar", { name: "选区工具" });

  fireEvent.keyDown(instance.view.dom, { key: "Tab" });
  expect(document.activeElement).toBe(button("粗体"));
  fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
  expect(document.activeElement).toBe(button("斜体"));
  fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
  expect(document.activeElement).toBe(button("粗体"));

  fireEvent.keyDown(document.activeElement!, { key: "Escape" });
  await waitFor(() => expect(toolbar()).toBeNull());
  expect(document.activeElement).toBe(instance.view.dom);
});

it("格式命令作用在选区上,已有的格式显示为按下", async () => {
  mount();
  const instance = await editor();
  select(instance, "剪辑组");
  await screen.findByRole("toolbar", { name: "选区工具" });

  fireEvent.click(button("粗体"));
  expect(instance.getMarkdown()).toContain("**剪辑组**");
  await waitFor(() => expect(button("粗体")).toHaveAttribute("aria-pressed", "true"));
  fireEvent.click(button("斜体"));
  expect(instance.isActive("italic")).toBe(true);
  fireEvent.click(button("删除线"));
  expect(instance.isActive("strike")).toBe(true);

  select(instance, "脚本");
  await screen.findByRole("toolbar", { name: "选区工具" });
  fireEvent.click(button("行内代码"));
  expect(instance.getMarkdown()).toContain("`脚本`");
});

it("加链接:输入地址回车;选中带链接的字再点就去掉", async () => {
  mount();
  const instance = await editor();
  select(instance, "链接文字");
  await screen.findByRole("toolbar", { name: "选区工具" });

  fireEvent.click(button("网页链接"));
  const input = screen.getByRole("textbox", { name: "网页链接" });
  fireEvent.change(input, { target: { value: "https://example.com/a" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(instance.getMarkdown()).toContain("[链接文字](https://example.com/a)");

  select(instance, "链接文字");
  await screen.findByRole("toolbar", { name: "选区工具" });
  fireEvent.click(button("去掉链接"));
  expect(instance.getMarkdown()).not.toContain("https://example.com/a");
});

it("转列表 / 待办;复制交出的是选中的纯文字", async () => {
  mount();
  const instance = await editor();
  select(instance, "剪辑组");
  await screen.findByRole("toolbar", { name: "选区工具" });

  fireEvent.click(button("复制"));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("剪辑组"));

  fireEvent.click(button("无序列表"));
  expect(instance.isActive("bulletList")).toBe(true);
  fireEvent.click(button("任务列表"));
  expect(instance.isActive("taskList")).toBe(true);
});

it("AI 动作带着这段选区交出去;问 AI、引用到对话也是", async () => {
  mount();
  const instance = await editor();
  select(instance, "剪辑组");
  await screen.findByRole("toolbar", { name: "选区工具" });

  fireEvent.click(button("AI 动作"));
  //: 名字下面那句说明是这一项的描述,不拼进名字。
  const polish = await screen.findByRole("menuitem", { name: "润色" });
  expect(polish).toHaveAccessibleDescription("让表达更通顺、更得体,意思不变");
  fireEvent.click(polish);
  expect(handlers.onAiAction).toHaveBeenCalledWith("polish", expect.objectContaining({ text: "剪辑组" }));

  //: 交给助手之后工具条收起;离开正文再回来选一段,它又出来。(在正文里按下鼠标也会让它重新出来,
  //: 但 jsdom 里 ProseMirror 的 mousedown 要用 elementFromPoint,这里走焦点那一路。)
  await waitFor(() => expect(toolbar()).toBeNull());
  act(() => { (instance.view.dom as HTMLElement).blur(); });
  select(instance, "节奏");
  await screen.findByRole("toolbar", { name: "选区工具" });
  fireEvent.click(button("引用到对话"));
  expect(handlers.onQuote).toHaveBeenCalledWith(expect.objectContaining({ text: "节奏" }));

  act(() => { (instance.view.dom as HTMLElement).blur(); });
  select(instance, "脚本");
  await screen.findByRole("toolbar", { name: "选区工具" });
  fireEvent.click(button("问 AI"));
  expect(handlers.onAskAi).toHaveBeenCalledWith(expect.objectContaining({ text: "脚本" }));
});

it("没选过音色:朗读走免费的 Edge 引擎、在本地播放,不建素材", async () => {
  mount();
  const instance = await editor();
  select(instance, "周一和剪辑组对了节奏");
  await screen.findByRole("toolbar", { name: "选区工具" });

  fireEvent.click(button("朗读"));

  await waitFor(() => expect(speech.fetchVoicePreview).toHaveBeenCalled());
  expect(speech.fetchVoicePreview).toHaveBeenCalledWith({
    workspace_id: "ws", engine: "builtin:edge", voice: "zh-CN-XiaoxiaoNeural", text: "周一和剪辑组对了节奏",
  });
  await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalled());
  expect(speech.synthesizeWithEngine).not.toHaveBeenCalled();
  expect(speech.readWithAgentVoice).not.toHaveBeenCalled();
});

it("在「语音对话」里选过音色:朗读跟着那把嗓子念(走后端朗读那条路),不再用 Edge", async () => {
  speech.agentVoice = { ...speech.agentVoice, engine: "openai", engine_voice: "alloy" };
  try {
    mount();
    const instance = await editor();
    select(instance, "周一和剪辑组对了节奏");
    await screen.findByRole("toolbar", { name: "选区工具" });

    fireEvent.click(button("朗读"));

    await waitFor(() => expect(speech.readWithAgentVoice).toHaveBeenCalledWith({ workspace_id: "ws", text: "周一和剪辑组对了节奏" }));
    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalled());
    expect(speech.fetchVoicePreview).not.toHaveBeenCalled();
  } finally {
    speech.agentVoice = { ...speech.agentVoice, engine: "", engine_voice: "" };
  }
});

it("存到笔记:打开现有的保存对话框,写进去的是选中的这段", async () => {
  mount();
  const instance = await editor();
  select(instance, "剪辑组");
  await screen.findByRole("toolbar", { name: "选区工具" });
  fireEvent.click(button("保存到笔记"));
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(screen.getByRole("dialog").textContent).toContain("存为新笔记");
});

it("窄屏收成「问 AI」+「更多」,其余都在「更多」菜单里", async () => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 480 });
  mount();
  const instance = await editor();
  select(instance, "剪辑组");
  await screen.findByRole("toolbar", { name: "选区工具" });
  expect(within(toolbar()!).queryByRole("button", { name: "粗体" })).toBeNull();
  expect(button("问 AI")).toBeInTheDocument();

  fireEvent.click(button("更多"));
  fireEvent.click(await screen.findByRole("menuitem", { name: "粗体" }));
  expect(instance.getMarkdown()).toContain("**剪辑组**");
});

it("加到画板:打开画板选择器", async () => {
  mount();
  const instance = await editor();
  select(instance, "剪辑组");
  await screen.findByRole("toolbar", { name: "选区工具" });
  fireEvent.click(button("加到画板"));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByRole("searchbox")).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: /新建画板/ })).toBeInTheDocument();
});

it("高亮:格式组里一颗按钮,点了加上、已高亮的再点取消;Mod+Shift+H 同样切换", async () => {
  mount();
  const instance = await editor();
  select(instance, "剪辑组");
  await screen.findByRole("toolbar", { name: "选区工具" });

  fireEvent.click(button("高亮"));
  expect(instance.getMarkdown()).toContain("==剪辑组==");
  await waitFor(() => expect(button("高亮")).toHaveAttribute("aria-pressed", "true"));
  fireEvent.click(button("高亮"));
  expect(instance.getMarkdown()).not.toContain("==");

  fireEvent.keyDown(instance.view.dom, { key: "H", code: "KeyH", keyCode: 72, ctrlKey: true, shiftKey: true });
  expect(instance.getMarkdown()).toContain("==剪辑组==");
  fireEvent.keyDown(instance.view.dom, { key: "H", code: "KeyH", keyCode: 72, ctrlKey: true, shiftKey: true });
  expect(instance.getMarkdown()).not.toContain("==");
});
