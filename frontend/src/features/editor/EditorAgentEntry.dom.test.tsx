/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
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
    return key;
  },
  usePreferences: () => ({ locale: "zh-CN" }),
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

vi.mock("@/components/agent/CanvasAgentChat", () => ({
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
      <EditorView workspace={workspace} project={project} onCreateProject={vi.fn()} creatingProject={false} />
    </QueryClientProvider>,
  );
}

describe("剪辑页智能体入口", () => {
  beforeEach(() => {
    localStorage.clear();
    Element.prototype.scrollIntoView = vi.fn();
    apiMocks.api.mockReset().mockImplementation((path: string) => {
      if (path.startsWith("/api/projects/") && path.endsWith("/sequences")) return Promise.resolve([sequence]);
      if (path.startsWith("/api/assets")) return Promise.resolve([]);
      return Promise.resolve([]);
    });
    apiMocks.listFonts.mockReset().mockResolvedValue([]);
  });

  it("从监视器操作条打开助手,并把当前项目与时间线传入上下文", async () => {
    const user = userEvent.setup();
    renderEditor();

    const trigger = await screen.findByRole("button", { name: "wfAgentTitle" });
    expect(screen.queryByTestId("editor-agent-panel")).toBeNull();

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("editor-agent-panel")).toHaveAttribute(
      "data-context",
      "project=宣传片;project_id=project-1;sequence=主时间线;sequence_id=sequence-1",
    );
    expect(localStorage.getItem("openstudio:tab:editor-agent")).toBe("on");
  });

  it("助手可从面板关闭,不会留下遮挡编辑区的空容器", async () => {
    const user = userEvent.setup();
    localStorage.setItem("openstudio:tab:editor-agent", "on");
    renderEditor();

    await user.click(await screen.findByRole("button", { name: "close-agent" }));

    expect(screen.queryByTestId("editor-agent-panel")).toBeNull();
    expect(localStorage.getItem("openstudio:tab:editor-agent")).toBe("off");
  });
});
