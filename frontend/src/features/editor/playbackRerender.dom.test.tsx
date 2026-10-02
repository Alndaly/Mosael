/** @vitest-environment jsdom */
/**
 * 播放时面板不能每帧整体重渲。
 *
 * 播放头一秒被写二十几次;字幕面板(每行一个 textarea)、逐字稿(上万个词按钮)、检查器、监视器此前都
 * 直接订阅它,于是每一帧都把整张列表 / 整个面板协调一遍 —— 长素材上播放一卡一卡的。现在它们只订阅
 * 「当前是哪一句 / 哪个词 / 哪几段在场」这类低频派生值:播放头在同一句里走,面板一次都不该提交。
 *
 * 用 React.Profiler 数提交次数:子树里没有任何组件重渲,Profiler 就不会回调。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

// 合成器每次监视器重渲都会拿到新的 props;把它换成一个计数的空壳,数的就是监视器的重渲次数。
const compositorRenders = vi.hoisted(() => ({ count: 0 }));
vi.mock("@/features/editor/playback/CanvasCompositor", () => ({
  CanvasCompositor: () => {
    compositorRenders.count += 1;
    return null;
  },
}));

import { Inspector } from "@/features/editor/Inspector";
import { Monitor } from "@/features/editor/Monitor";
import { SubtitlePanel } from "@/features/editor/SubtitlePanel";
import { TranscriptPanel } from "@/features/editor/TranscriptPanel";
import { useEditorStore } from "@/features/editor/editorStore";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const originalFetch = globalThis.fetch;
beforeEach(() => useEditorStore.setState({ playhead: 0, playing: false, selectedClipIds: [] }));
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function withClient(node: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>;
}

function countCommits(node: React.ReactNode) {
  const commits = { count: 0 };
  const view = render(
    withClient(
      <React.Profiler id="panel" onRender={() => (commits.count += 1)}>
        {node}
      </React.Profiler>,
    ),
  );
  return { commits, view };
}

/** 模拟播放:在 [from, to) 里走 n 步。 */
function play(from: number, to: number, steps = 20) {
  for (let i = 0; i < steps; i++) act(() => useEditorStore.getState().setPlayhead(from + ((to - from) * i) / steps));
}

describe("字幕面板", () => {
  const subtitles = (n: number) =>
    ({
      id: "s1", workspace_id: "w1", revision: 1,
      tracks: [{
        id: "t1", kind: "subtitle",
        clips: Array.from({ length: n }, (_, i) => ({
          id: `c${i}`, asset_id: null, asset_kind: "", timeline_start: i * 2, src_in: 0, src_out: 1.5, speed: 1, text_override: `第${i}条`,
        })),
      }],
    }) as never;

  it("播放头在同一条字幕里走:面板一次都不提交;换到下一条才提交", () => {
    const { commits } = countCommits(
      <SubtitlePanel sequence={subtitles(2000)} onSetText={vi.fn()} onAddSubtitle={vi.fn()} onDeleteClip={vi.fn()} />,
    );
    commits.count = 0;
    play(0.1, 1.4);
    expect(commits.count).toBe(0);
    act(() => useEditorStore.getState().setPlayhead(2.1));
    expect(commits.count).toBeGreaterThan(0);
  });

  it("两千条字幕只渲染视口里的几十个 textarea", () => {
    render(withClient(<SubtitlePanel sequence={subtitles(2000)} onSetText={vi.fn()} onAddSubtitle={vi.fn()} onDeleteClip={vi.fn()} />));
    const rendered = document.querySelectorAll("textarea").length;
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(100);
  });
});

describe("逐字稿", () => {
  function serveTranscript(sentences: number, wordsPerSentence: number) {
    const transcript = {
      id: "tr1", language: "zh",
      segments: Array.from({ length: sentences }, (_, s) => ({
        id: `seg${s}`, start_time: s * 5, end_time: s * 5 + 4, text: `句${s}`, speaker: null,
        tokens: Array.from({ length: wordsPerSentence }, (_, w) => ({
          start_time: s * 5 + w * (4 / wordsPerSentence),
          end_time: s * 5 + (w + 1) * (4 / wordsPerSentence),
          text: `词${s}-${w}`,
        })),
      })),
    };
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes("/transcript") ? transcript : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as never;
  }
  const sequence = {
    id: "s1", workspace_id: "w1", revision: 1,
    tracks: [{ id: "t1", kind: "video", clips: [{ id: "c1", asset_id: "a1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 5000, speed: 1 }] }],
  } as never;

  it("一万个词:只渲染视口里的句子;播放头在同一个词里走不提交,换词只重渲那一句", async () => {
    serveTranscript(1000, 10);
    const { commits } = countCommits(<TranscriptPanel sequence={sequence} onCutSegment={vi.fn()} />);
    await screen.findByText("词0-0");
    expect(document.querySelectorAll("[data-flat]").length).toBeLessThan(1000);

    commits.count = 0;
    // 第一个词是 [0, 0.4):在它里面走。
    play(0.01, 0.39);
    expect(commits.count).toBe(0);
    // 换到下一个词:要提交(高亮挪过去)。
    act(() => useEditorStore.getState().setPlayhead(0.45));
    expect(commits.count).toBeGreaterThan(0);
    expect(screen.getByText("词0-1").className).toContain("font-medium");
  });
});

describe("检查器", () => {
  const base = { id: "clip-1", asset_id: "asset-1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 10, speed: 1, gain: 1, muted: false, effects: {} };
  const assets = [{ id: "asset-1", name: "Video", kind: "video" }] as never;

  it("没有关键帧的片段:播放时一次都不提交", () => {
    const { commits } = countCommits(
      <Inspector workspaceId="w1" selectedClip={{ ...base, transform: {} } as never} assets={assets} onDeleteClip={vi.fn()} onSetEffects={vi.fn()} />,
    );
    commits.count = 0;
    play(0, 9);
    expect(commits.count).toBe(0);
  });

  it("有关键帧的片段:显示值要跟着进度走,所以会提交", () => {
    const transform = { scale: 1, keyframes: [{ t: 0, scale: 1 }, { t: 1, scale: 2 }] };
    const { commits } = countCommits(
      <Inspector workspaceId="w1" selectedClip={{ ...base, transform } as never} assets={assets} onDeleteClip={vi.fn()} onSetEffects={vi.fn()} />,
    );
    commits.count = 0;
    play(0, 9);
    expect(commits.count).toBeGreaterThan(0);
  });
});

describe("监视器", () => {
  const asset = { id: "a1", name: "v", kind: "video", media_info: { proxy_status: "ready" }, proxy_expected: true };
  const sequence = {
    id: "s1", workspace_id: "w1", revision: 1, width: 1920, height: 1080, fps: 30,
    tracks: [{
      id: "v1", kind: "video", position: 0,
      clips: [
        { id: "c1", asset_id: "a1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 10, speed: 1, effects: {}, transform: {} },
        { id: "c2", asset_id: "a1", asset_kind: "video", timeline_start: 10, src_in: 10, src_out: 20, speed: 1, effects: {}, transform: {} },
      ],
    }],
  } as never;

  it("播放头在同一段里走:监视器本体不重渲(进度条和时间码是各自的小订阅者)", () => {
    render(withClient(<Monitor sequence={sequence} assets={[asset] as never} />));
    compositorRenders.count = 0;
    play(1, 8);
    expect(compositorRenders.count).toBe(0);
    // 走到预热窗口里(下一段开头前 0.8 秒内):预热集合变了,才重渲。
    act(() => useEditorStore.getState().setPlayhead(9.5));
    expect(compositorRenders.count).toBeGreaterThan(0);
  });
});
