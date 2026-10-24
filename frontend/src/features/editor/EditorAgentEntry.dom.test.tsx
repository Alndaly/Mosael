/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  resize: null as ResizeObserverCallback | null,
  api: vi.fn(),
  listFonts: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => {
    if (key === "editorAgentContext") {
      return "project={project};project_id={projectId};sequence={sequence};sequence_id={sequenceId}";
    }
    if (key === "wfAgentTitle") return "AI 助手";
    return key;
  },
  usePreferences: () => ({ locale: "zh-CN" }),
}));

//: 「替换媒体」的挑选弹窗(AssetGridPicker)一直挂着;看大图的灯箱在应用根上,这里不挂,给一个桩。
vi.mock("@/components/app/image-preview", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/app/image-preview")>()),
  useImagePreview: () => ({ openImagePreview: () => {}, isImagePreviewOpen: false }),
}));

vi.mock("@/features/editor/useEditorPanels", () => ({
  useEditorPanels: () => ({
    tab: "media",
    setTab: vi.fn(),
    compact: false,
    sizes: { left: { media: 252, transcript: 420, subtitle: 320, voice: 320 }, right: 264, timeline: 252 },
    leftWidth: 252,
    startDrag: () => vi.fn(),
  }),
}));

vi.mock("@/features/agent/CanvasAgentChat", () => ({
  CanvasAgentChat: ({ contextLine, onClose }: { contextLine: string; onClose: () => void }) => (
    <aside data-testid="editor-agent-panel" data-context={contextLine}>
      <button type="button" onClick={onClose}>close-agent</button>
    </aside>
  ),
}));

vi.mock("@/features/editor/MediaPool", () => ({
  MediaPool: ({ tabs }: { tabs: React.ReactNode }) => <section>{tabs}</section>,
}));
vi.mock("@/features/editor/Monitor", () => ({ Monitor: () => <div data-testid="monitor" /> }));
vi.mock("@/features/editor/timeline/Timeline", () => ({
  Timeline: () => <div data-testid="timeline" />,
  trackAcceptsAsset: () => true,
}));
vi.mock("@/features/editor/FontFaces", () => ({ FontFaces: () => null }));

import type { Project, Sequence, Workspace } from "@/api/client";
import { EditorView } from "@/features/editor/EditorView";
import { TooltipProvider } from "@/components/ui/tooltip";
import { RecordingProvider } from "@/features/media/RecordingProvider";
import { readHint } from "@/test/hint";

const workspace = { id: "workspace-1", name: "工作区" } as Workspace;
const project = { id: "project-1", name: "宣传片" } as Project;
const sequence = {
  id: "sequence-1",
  name: "主时间线",
  project_id: project.id,
  workspace_id: workspace.id,
  width: 1920,
  height: 1080,
  fps: 30,
  tracks: [],
  can_undo: false,
  can_redo: false,
} as unknown as Sequence;

function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider><RecordingProvider workspaceId={workspace.id}>
        <EditorView workspace={workspace} project={project} />
      </RecordingProvider></TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("剪辑页智能体入口", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("ResizeObserver", class {
      constructor(callback: ResizeObserverCallback) { apiMocks.resize = callback; }
      observe() {}
      disconnect() {}
    });
    Element.prototype.scrollIntoView = vi.fn();
    apiMocks.api.mockReset().mockImplementation((path: string) => {
      if (path.startsWith("/api/projects/") && path.endsWith("/sequences")) return Promise.resolve([sequence]);
      if (path.startsWith("/api/assets")) return Promise.resolve([]);
      return Promise.resolve([]);
    });
    apiMocks.listFonts.mockReset().mockResolvedValue([]);
  });

  it("从顶部工具栏打开助手,并把当前项目与时间线传入上下文", async () => {
    const user = userEvent.setup();
    renderEditor();

    const trigger = await screen.findByRole("button", { name: "AI 助手" });
    expect(screen.queryByTestId("editor-agent-panel")).toBeNull();

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("editor-layout")).toHaveStyle({
      gridTemplateColumns: "252px minmax(0, 1fr) 400px",
    });
    expect(screen.getByTestId("editor-agent-slot")).toHaveClass("grid");
    expect(screen.getByTestId("editor-agent-slot")).not.toHaveClass("absolute");
    expect(screen.getByTestId("editor-agent-panel")).toHaveAttribute(
      "data-context",
      "project=宣传片;project_id=project-1;sequence=主时间线;sequence_id=sequence-1",
    );
    expect(localStorage.getItem("mosael:tab:editor-agent")).toBe("on");
  });

  it("只有图标:按钮里没有「AI 助手」这几个字", async () => {
    renderEditor();

    const trigger = await screen.findByRole("button", { name: "AI 助手" });

    expect(trigger.querySelector("svg")).not.toBeNull();
    expect(trigger.textContent).toBe("");
    expect(screen.queryByText("AI 助手")).toBeNull();
  });

  it("图标没有文字,读屏和悬停仍有名字:aria-label 与 Hint 都是「AI 助手」", async () => {
    renderEditor();

    const trigger = await screen.findByRole("button", { name: "AI 助手" });

    expect(trigger).toHaveAttribute("aria-label", "AI 助手");
    expect(await readHint(trigger)).toContain("AI 助手");
  });

  it("和右边那颗 ✨(在播放头加花字)不是同一个图标", async () => {
    renderEditor();

    const agent = await screen.findByRole("button", { name: "AI 助手" });
    const sparkles = screen.getByRole("button", { name: "addTextAtPlayhead" });
    const iconClass = (element: HTMLElement) => element.querySelector("svg")?.getAttribute("class") ?? "";

    expect(iconClass(agent)).toContain("lucide-bot");
    expect(iconClass(sparkles)).toContain("lucide-sparkles");
    expect(iconClass(agent)).not.toBe(iconClass(sparkles));
  });

  it("窄工作台把助手改为覆盖层,恢复宽度后继续停靠", async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(await screen.findByRole("button", { name: "AI 助手" }));
    act(() => apiMocks.resize?.([{ contentRect: { width: 700 } } as ResizeObserverEntry], {} as ResizeObserver));
    expect(screen.getByTestId("editor-layout")).toHaveStyle({ gridTemplateColumns: "252px minmax(0, 1fr)" });
    expect(screen.getByTestId("editor-agent-slot")).toHaveClass("absolute");
    expect(screen.getByTestId("editor-agent-panel")).toBeInTheDocument();
    act(() => apiMocks.resize?.([{ contentRect: { width: 1200 } } as ResizeObserverEntry], {} as ResizeObserver));
    expect(screen.getByTestId("editor-layout")).toHaveStyle({ gridTemplateColumns: "252px minmax(0, 1fr) 400px" });
    expect(screen.getByTestId("editor-agent-slot")).not.toHaveClass("absolute");
  });

  it("助手可从面板关闭,不会留下遮挡编辑区的空容器", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael:tab:editor-agent", "on");
    renderEditor();

    await user.click(await screen.findByRole("button", { name: "close-agent" }));

    expect(screen.queryByTestId("editor-agent-panel")).toBeNull();
    expect(localStorage.getItem("mosael:tab:editor-agent")).toBe("off");
  });
});
