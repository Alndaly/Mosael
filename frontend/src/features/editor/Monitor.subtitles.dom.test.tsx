/** @vitest-environment jsdom */
/**
 * 预览里的双语字幕:分两条字幕轨时,两行合成**一个**字幕元素,按序列字幕样式定位,原文(时间线上靠上的那条轨)
 * 在上、译文在下 —— 和同一条轨里写两行是同一个元素。此前第二条轨换到画面另一头(底部样式下译文画在顶上)。
 *
 * 导出那一侧把同一框字渲成一张 PNG / 一条 libass Dialogue(backend/tests/test_bilingual_subtitle_lanes.py
 * 真渲量像素);合成规则两侧由 contracts/text-layer-cases.json 钉住。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/features/editor/playback/CanvasCompositor", () => ({ CanvasCompositor: () => null }));
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

import { Monitor } from "@/features/editor/Monitor";
import { useEditorStore } from "@/features/editor/editorStore";

beforeEach(() => useEditorStore.setState({ playhead: 1, playing: false, selectedClipIds: [] }));

const asset = { id: "a1", name: "v", kind: "video", media_info: { proxy_status: "ready" }, proxy_expected: true };

function cue(id: string, text: string, start: number, end: number) {
  return { id, asset_id: null, asset_kind: "", timeline_start: start, src_in: 0, src_out: end - start, speed: 1, text_override: text };
}

function sequence(subtitleTracks: { id: string; position: number; clips: ReturnType<typeof cue>[] }[]) {
  return {
    id: "s1", workspace_id: "w1", revision: 1, width: 1920, height: 1080, fps: 30,
    subtitle_style: { position: "bottom", offset: 8 },
    tracks: [
      {
        id: "v1", kind: "video", position: 0,
        clips: [{ id: "c1", asset_id: "a1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 10, speed: 1, effects: {}, transform: {} }],
      },
      ...subtitleTracks.map((track) => ({ ...track, kind: "subtitle", hidden: false })),
    ],
  } as never;
}

function renderMonitor(seq: never) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Monitor sequence={seq} assets={[asset] as never} />
    </QueryClientProvider>,
  );
}

describe("预览里的双语字幕", () => {
  it("两条字幕轨同时有字:一个字幕元素,原文在上、译文在下,和一条轨里写两行一模一样", () => {
    const twoTracks = renderMonitor(
      sequence([
        { id: "zh", position: 1, clips: [cue("nihao", "你好", 0, 2)] },
        { id: "en", position: 2, clips: [cue("hello", "Hello", 0, 2)] },
      ]),
    );
    const stacked = screen.getAllByTestId("monitor-subtitle");
    expect(stacked).toHaveLength(1);
    expect(stacked[0].textContent).toBe("你好\nHello");
    // 底部样式:框的下沿贴着 8%,第二行往上长 —— 不再有一行跑到画面顶上。
    expect(stacked[0].style.bottom).toBe("8%");
    const twoTracksHtml = stacked[0].outerHTML;
    twoTracks.unmount();

    renderMonitor(sequence([{ id: "zh", position: 1, clips: [cue("both", "你好\nHello", 0, 2)] }]));
    expect(screen.getByTestId("monitor-subtitle").outerHTML).toBe(twoTracksHtml);
  });

  it("播放头走到只剩一道的地方:框里只剩那一行;都不在场时不画字幕", () => {
    renderMonitor(
      sequence([
        { id: "zh", position: 1, clips: [cue("nihao", "你好", 0, 3)] },
        { id: "en", position: 2, clips: [cue("hello", "Hello", 1.5, 4)] },
      ]),
    );
    expect(screen.getByTestId("monitor-subtitle").textContent).toBe("你好");
    act(() => useEditorStore.getState().setPlayhead(2));
    expect(screen.getByTestId("monitor-subtitle").textContent).toBe("你好\nHello");
    act(() => useEditorStore.getState().setPlayhead(3));
    expect(screen.getByTestId("monitor-subtitle").textContent).toBe("Hello");
    act(() => useEditorStore.getState().setPlayhead(5));
    expect(screen.queryByTestId("monitor-subtitle")).toBeNull();
  });
});
