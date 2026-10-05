/** @vitest-environment jsdom */

/**
 * 从访达 / 桌面把文件拖进智能体对话,和点 📎 选了这些文件是**同一件事**;粘贴也是。
 *
 * 两个对话框(AI 工作台、画布助手)都挂着同一套附件逻辑(composerAttachments),这里对两边各跑一遍:
 * 此前 📎 能附文件,拖进来什么也不发生 —— 而两份代码里的注释都写着「选文件 / 拖放 / 粘贴」。
 *
 * 附件逻辑和输入框(ChatComposer,真的 TipTap 编辑器)都用真的,只把后端、周边的按钮换掉:
 * 要验证的正是「拖放 / 粘贴 → 同一个 accept → 进素材库、出现在附件条里」这条线接没接上。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  importAsset: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  API_BASE: "http://backend.test",
  getAuthToken: () => null,
  agentManifest: vi.fn(async () => ({ version: "1" })),
  listAgentTools: vi.fn(async () => []),
  listAgentSessions: vi.fn(async () => [{ id: "s1", workspace_id: "w1", title: "我的对话", is_mine: true }]),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  deleteAgentSession: vi.fn(),
  getAgentSession: vi.fn(async () => ({ id: "s1", workspace_id: "w1", title: "我的对话", status: "idle", is_mine: true })),
  listAgentMessages: vi.fn(async () => []),
  listAgentQueue: vi.fn(async () => []),
  listAgentUsageEvents: vi.fn(async () => []),
  sendAgentMessage: vi.fn(),
  compactAgentSession: vi.fn(),
  dropQueuedMessage: vi.fn(),
  steerQueuedMessage: vi.fn(),
  stopAgentSession: vi.fn(),
  importAsset: mocks.importAsset,
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
}));
//: 报错文案带上 {name} 占位符:被拒绝的文件必须报出是哪一个(同 composerAttachments 的测试)。
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key.startsWith("composerFile") ? `${key}:{name}` : key),
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));
vi.mock("sonner", () => ({ toast: { error: mocks.toastError, message: vi.fn(), success: vi.fn() } }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
vi.mock("@/features/notes/useNoteAttachments", () => ({
  useNoteAttachments: () => ({ hasNotes: false, context: "", summary: "", chips: [], dialog: null, trigger: null, clear() {} }),
}));
vi.mock("@/features/ai-studio/SessionList", () => ({ SessionList: () => null }));
vi.mock("@/features/agent/ChatBubble", () => ({ ChatBubble: () => null }));
vi.mock("@/features/agent/DictateButton", () => ({ DictateButton: () => null }));
vi.mock("@/features/agent/ModelPicker", () => ({ ModelPicker: () => null }));
vi.mock("@/features/agent/SessionSettingsMenu", () => ({ SessionSettingsMenu: () => null }));
vi.mock("@/features/agent/PendingDecisions", () => ({
  SessionDecisions: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PendingDecisions: () => null,
  JumpToLatestOrDecision: () => null,
}));
vi.mock("@/features/agent/QueuedMessages", () => ({ QueuedMessages: () => null }));
vi.mock("@/features/agent/trace/TraceView", () => ({ TraceView: () => null, TraceStatsBar: () => null }));
vi.mock("@/features/agent/trace/traceModel", () => ({ buildTurns: () => [] }));

import { ChatWorkspace } from "@/features/ai-studio/ChatWorkspace";
import { CanvasAgentChat } from "./CanvasAgentChat";

class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  window.localStorage.clear();
  mocks.importAsset.mockReset();
  mocks.toastError.mockReset();
  vi.stubGlobal("ResizeObserver", NoopObserver);
  vi.stubGlobal("IntersectionObserver", NoopObserver);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 503 })));
  //: jsdom 没有 elementFromPoint,ProseMirror 算落点要用:指到编辑器的第一段上。
  document.elementFromPoint = () => document.querySelector(".ProseMirror p");
});

function withClient(node: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

/** 每个对话框:渲染出来,等会话落定,交出一块「对话区里的东西」当拖放落点。 */
const HOSTS: Record<string, () => Promise<{ inside: HTMLElement; alsoInside: HTMLElement }>> = {
  AI工作台: async () => {
    render(withClient(<ChatWorkspace workspace={{ id: "w1", name: "工作区" } as never} />));
    await screen.findAllByText("我的对话");
    //: 消息区里的空态和输入卡里的编辑器:两者之间来回挪,提示不能跟着闪。
    return { inside: await screen.findByText("studioChatStart"), alsoInside: await editorDom() };
  },
  画布助手: async () => {
    render(
      withClient(
        <CanvasAgentChat
          contextLine=""
          emptyHint="empty-hint"
          placeholder="placeholder"
          rectKey="test.canvas.agent"
          workspaceId="w1"
          mode="docked"
          onModeChange={() => {}}
          onClose={() => {}}
        />,
      ),
    );
    await screen.findAllByText("我的对话");
    return { inside: await screen.findByText("empty-hint"), alsoInside: await editorDom() };
  },
};

async function editorDom(): Promise<HTMLElement> {
  return waitFor(() => {
    const dom = document.querySelector(".ProseMirror") as HTMLElement | null;
    expect(dom).toBeTruthy();
    return dom!;
  });
}

/** jsdom 没有 DataTransfer:拖拽事件里只放这套代码读得到的那几样。 */
function drag(
  target: Element,
  type: "dragenter" | "dragover" | "dragleave" | "drop",
  init: { types: string[]; files?: File[]; data?: Record<string, string>; relatedTarget?: EventTarget | null },
) {
  const files = init.files ?? [];
  const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: 1, clientY: 1 });
  Object.defineProperty(event, "dataTransfer", {
    value: {
      types: init.types,
      files,
      items: files.map((file) => ({ kind: "file", type: file.type })),
      dropEffect: "none",
      getData: (format: string) => init.data?.[format] ?? "",
    },
  });
  if ("relatedTarget" in init) Object.defineProperty(event, "relatedTarget", { value: init.relatedTarget });
  act(() => {
    target.dispatchEvent(event);
  });
  return event;
}

function paste(target: HTMLElement, data: { text?: string; files?: File[] }) {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", {
    value: { files: data.files ?? [], types: [], getData: (type: string) => (type === "text/plain" ? (data.text ?? "") : "") },
  });
  act(() => {
    target.focus();
    target.dispatchEvent(event);
  });
  return event;
}

const png = () => new File(["png"], "shot.png", { type: "image/png" });

describe.each(Object.keys(HOSTS))("%s:从系统拖文件进来", (host) => {
  it("拖着文件悬在对话区上出现「松手添加到对话」;在里面挪来挪去不灭,拖出去才灭", async () => {
    const { inside, alsoInside } = await HOSTS[host]!();
    expect(screen.queryByText("composerDropHint")).toBeNull();

    const enter = drag(inside, "dragenter", { types: ["Files"], files: [png()] });
    expect(enter.defaultPrevented).toBe(true);
    expect(screen.getByText("composerDropHint")).toBeTruthy();
    // 不拦 dragover 的话浏览器会直接打开这个文件,把整个应用顶掉。
    expect(drag(inside, "dragover", { types: ["Files"], files: [png()] }).defaultPrevented).toBe(true);

    //: 从消息区挪到输入框:离开的那个元素报一次 dragleave,但 relatedTarget 还在对话区里。
    drag(inside, "dragleave", { types: ["Files"], relatedTarget: alsoInside });
    drag(alsoInside, "dragenter", { types: ["Files"], files: [png()] });
    expect(screen.getByText("composerDropHint")).toBeTruthy();

    drag(alsoInside, "dragleave", { types: ["Files"], relatedTarget: document.body });
    expect(screen.queryByText("composerDropHint")).toBeNull();
  });

  it("松手:和 📎 选中同样的文件一样 —— 图片进素材库、出现在附件条里,提示消失", async () => {
    mocks.importAsset.mockResolvedValue({ id: "a1", name: "shot.png", kind: "image" });
    const { inside } = await HOSTS[host]!();
    const file = png();

    drag(inside, "dragenter", { types: ["Files"], files: [file] });
    const drop = drag(inside, "drop", { types: ["Files"], files: [file] });

    expect(drop.defaultPrevented).toBe(true);
    expect(screen.queryByText("composerDropHint")).toBeNull();
    await waitFor(() => expect(mocks.importAsset).toHaveBeenCalledWith({ workspaceId: "w1", file }));
    expect(await screen.findByRole("button", { name: "shot.png" })).toBeTruthy();
  });

  it("松手在输入框上也算数,不会被编辑器吞掉或当成一段字插进正文", async () => {
    mocks.importAsset.mockResolvedValue({ id: "a1", name: "shot.png", kind: "image" });
    const { alsoInside: editor } = await HOSTS[host]!();
    const file = png();

    drag(editor, "dragenter", { types: ["Files"], files: [file] });
    //: 从网页 / 某些文件管理器拖出来的文件还附带一条链接;编辑器不认领的话会把它当正文插进来。
    drag(editor, "drop", {
      types: ["Files", "text/uri-list"],
      files: [file],
      data: { "text/uri-list": "file:///Users/me/Desktop/shot.png" },
    });

    await waitFor(() => expect(mocks.importAsset).toHaveBeenCalledWith({ workspaceId: "w1", file }));
    expect(editor.textContent).toBe("");
  });

  it("收不了的文件和 📎 选到时一样报出是哪一个,而不是松手后什么都没发生", async () => {
    const { inside } = await HOSTS[host]!();
    const zip = new File(["x"], "bundle.zip", { type: "application/zip" });

    drag(inside, "dragenter", { types: ["Files"], files: [zip] });
    drag(inside, "drop", { types: ["Files"], files: [zip] });

    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledWith(expect.stringContaining("bundle.zip")));
    expect(mocks.importAsset).not.toHaveBeenCalled();
  });

  it("页面里拖一段字(不带文件)不亮提示、不拦、不附任何东西", async () => {
    const { inside } = await HOSTS[host]!();

    const enter = drag(inside, "dragenter", { types: ["text/plain"] });
    const over = drag(inside, "dragover", { types: ["text/plain"] });
    expect(screen.queryByText("composerDropHint")).toBeNull();
    const drop = drag(inside, "drop", { types: ["text/plain"] });

    expect([enter, over, drop].some((event) => event.defaultPrevented)).toBe(false);
    expect(mocks.importAsset).not.toHaveBeenCalled();
    expect(mocks.toastError).not.toHaveBeenCalled();
  });
});

describe.each(Object.keys(HOSTS))("%s:粘贴", (host) => {
  it("粘贴一张截图:进素材库、出现在附件条里", async () => {
    mocks.importAsset.mockResolvedValue({ id: "a2", name: "pasted.png", kind: "image" });
    const { alsoInside: editor } = await HOSTS[host]!();

    const event = paste(editor, { files: [new File(["png"], "", { type: "image/png" })] });

    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(mocks.importAsset).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("button", { name: "pasted.png" })).toBeTruthy();
    expect(editor.textContent).toBe("");
  });

  it("粘贴一段文字:照常进输入框,不当附件", async () => {
    const { alsoInside: editor } = await HOSTS[host]!();

    paste(editor, { text: "把第二幕剪短一点" });

    await waitFor(() => expect(editor.textContent).toBe("把第二幕剪短一点"));
    expect(mocks.importAsset).not.toHaveBeenCalled();
  });
});
