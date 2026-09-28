/** @vitest-environment jsdom */
/**
 * 检查器的分隔线只由节画、只画在节的上边。
 *
 * 调色页此前在「作用于 …」那行底下自带一道 border-b,紧跟着「风格预设」那一节的 border-t:
 * 两道线夹出一条空带。属性页没有这个毛病 —— 两页各写各的分隔,节奏就对不上。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  listLuts: vi.fn(async () => []),
}));
vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { Inspector } from "./Inspector";

const clip = {
  id: "clip-1", asset_id: "asset-1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 5, speed: 1,
  gain: 1, muted: false, effects: {}, transform: {},
} as never;
const sequence = { id: "seq-1", name: "Sequence", revision: 1, width: 1920, height: 1080, fps: 30 } as never;
const assets = [{ id: "asset-1", name: "Video", kind: "video" }] as never;

function renderInspector() {
  const { container } = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Inspector
        sequence={sequence}
        workspaceId="w1"
        selectedClip={clip}
        assets={assets}
        onDeleteClip={vi.fn()}
        onSetEffects={vi.fn()}
        onSetSpeed={vi.fn()}
        onSetGain={vi.fn()}
        onSetTransform={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return container;
}

/** 面板正文(面板头之后那一块)里,谁画了分隔线。 */
function dividers(container: HTMLElement) {
  const body = container.querySelector("section.editor-pane > :nth-child(2)") as HTMLElement;
  const drawn = [...body.querySelectorAll<HTMLElement>("*")].filter((el) => /(^|\s)border-[tb](\s|$)/.test(el.className));
  return { body, drawn };
}

describe("检查器的分隔线", () => {
  for (const tab of ["inspectorProps", "colorGrade"] as const) {
    it(`${tab}:只有节画线、只画上边,第一行不带线`, async () => {
      const container = renderInspector();
      await userEvent.click(screen.getByRole("tab", { name: tab }));
      const { body, drawn } = dividers(container);
      expect(drawn.length).toBeGreaterThan(1);
      for (const el of drawn) {
        expect(el.tagName, el.className).toBe("SECTION");
        expect(el.className).toMatch(/(^|\s)border-t(\s|$)/);
        expect(el.className).not.toMatch(/(^|\s)border-b(\s|$)/);
      }
      expect(drawn).not.toContain(body.firstElementChild);
    });
  }
});

/**
 * 区块按**素材类型**出,不按「是不是文字」一刀切:音频片段此前也有「调色」页签、变换 / 关键帧和
 * 画面淡变,图片片段也有音量和音频淡变 —— 调了没有任何效果,用户只会以为坏了。
 */
describe("检查器按素材类型出区块", () => {
  // 页签是记住的(上面那组测试点过「调色」),每条从属性页起步。
  beforeEach(() => localStorage.clear());
  function renderKind(kind: string, extra: Record<string, unknown> = {}) {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Inspector
          sequence={sequence}
          workspaceId="w1"
          selectedClip={{ ...(clip as object), asset_kind: kind, ...extra } as never}
          assets={[{ id: "asset-1", name: "A", kind }] as never}
          onDeleteClip={vi.fn()}
          onSetEffects={vi.fn()}
          onSetSpeed={vi.fn()}
          onSetGain={vi.fn()}
          onSetTransform={vi.fn()}
          onSetText={vi.fn()}
        />
      </QueryClientProvider>,
    );
  }

  it("视频:画面和声音的区块都有", () => {
    renderKind("video");
    expect(screen.getByRole("tab", { name: "colorGrade" })).toBeInTheDocument();
    expect(screen.getByText("transformTitle")).toBeInTheDocument();
    expect(screen.getByText("clipAudio")).toBeInTheDocument();
    expect(screen.getByText("videoFade")).toBeInTheDocument();
    expect(screen.getByText("audioFade")).toBeInTheDocument();
  });

  it("音频:没有调色页签、变换和画面淡变,只有音量和音频淡变", () => {
    renderKind("audio");
    expect(screen.queryByRole("tab", { name: "colorGrade" })).toBeNull();
    expect(screen.queryByText("transformTitle")).toBeNull();
    expect(screen.queryByText("videoFade")).toBeNull();
    expect(screen.getByText("clipAudio")).toBeInTheDocument();
    expect(screen.getByText("audioFade")).toBeInTheDocument();
  });

  it("图片:有调色和变换,没有音量和音频淡变", () => {
    renderKind("image");
    expect(screen.getByRole("tab", { name: "colorGrade" })).toBeInTheDocument();
    expect(screen.getByText("transformTitle")).toBeInTheDocument();
    expect(screen.getByText("videoFade")).toBeInTheDocument();
    expect(screen.queryByText("clipAudio")).toBeNull();
    expect(screen.queryByText("audioFade")).toBeNull();
  });

  it("记住的是调色页,选中音频片段时显示属性页", () => {
    localStorage.setItem("mosael:tab:editor-inspector", "color");
    renderKind("audio");
    expect(screen.getByText("clipAudio")).toBeInTheDocument();
  });
});
