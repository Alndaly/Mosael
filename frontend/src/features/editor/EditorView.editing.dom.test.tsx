/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 剪辑页的编辑手势,走真实的 EditorView:快捷键 → 选中/播放头 → 发出去的那条请求。
 *
 * 只把画面重的几块(时间线、监视器、素材池)换成桩 —— 时间线的桩把收到的回调交出来,好让测试
 * 像时间线那样调它们;请求层(@/api/client)换成记录调用的桩。被测的换算、选中、键位判定都是真的。
 */

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  listFonts: vi.fn(),
  splitClip: vi.fn(),
  undoSequence: vi.fn(),
  redoSequence: vi.fn(),
  moveClip: vi.fn(),
  moveClipsBatch: vi.fn(),
  trimClip: vi.fn(),
  setClipTransform: vi.fn(),
  splitClipAtPointsBatch: vi.fn(),
  addTrack: vi.fn(),
  timelineProps: null as Record<string, unknown> | null,
  monitorProps: null as Record<string, unknown> | null,
  transcriptProps: null as Record<string, unknown> | null,
  panelTab: "media",
}));

const toasts = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn(), message: vi.fn() }));
vi.mock("sonner", () => ({ toast: toasts }));

vi.mock("@/api/client", async (importOriginal) => {
  const { timelineProps: _timeline, monitorProps: _monitor, transcriptProps: _transcript, panelTab: _tab, ...apiMocks } = mocks;
  return { ...(await importOriginal<typeof import("@/api/client")>()), ...apiMocks };
});

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh-CN" }) }));

vi.mock("@/features/editor/useEditorPanels", () => ({
  useEditorPanels: () => ({
    tab: mocks.panelTab,
    setTab: vi.fn(),
    compact: false,
    sizes: { left: { media: 252, transcript: 420, subtitle: 320, voice: 320 }, right: 264, timeline: 252 },
    leftWidth: 252,
    startDrag: () => vi.fn(),
  }),
}));
vi.mock("@/features/agent/CanvasAgentChat", () => ({ CanvasAgentChat: () => null }));
vi.mock("@/features/editor/MediaPool", () => ({ MediaPool: () => <section /> }));
vi.mock("@/features/editor/Monitor", () => ({
  Monitor: (props: Record<string, unknown>) => {
    mocks.monitorProps = props;
    return <div data-testid="monitor" />;
  },
}));
vi.mock("@/features/editor/timeline/Timeline", () => ({
  Timeline: (props: Record<string, unknown>) => {
    mocks.timelineProps = props;
    return <div data-testid="timeline" />;
  },
  trackAcceptsAsset: () => true,
}));
vi.mock("@/features/editor/FontFaces", () => ({ FontFaces: () => null }));
vi.mock("@/features/editor/TranscriptPanel", () => ({
  TranscriptPanel: (props: Record<string, unknown>) => {
    mocks.transcriptProps = props;
    return null;
  },
}));

import type { Clip, Project, Sequence, Track, Workspace } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { EditorView } from "@/features/editor/EditorView";
import { useEditorStore } from "@/features/editor/editorStore";
import { RecordingProvider } from "@/features/media/RecordingProvider";

const workspace = { id: "w1", name: "W" } as Workspace;
const project = { id: "p1", name: "P" } as Project;

function clip(id: string, trackId: string, start: number, srcIn: number, srcOut: number, extra: Partial<Clip> = {}): Clip {
  return {
    id,
    track_id: trackId,
    asset_id: "a1",
    asset_kind: "video",
    timeline_start: start,
    src_in: srcIn,
    src_out: srcOut,
    speed: 1,
    gain: 1,
    muted: false,
    text_override: null,
    effects: {},
    transform: {},
    ...extra,
  } as Clip;
}

function track(id: string, kind: string, position: number, clips: Clip[], extra: Partial<Track> = {}): Track {
  return { id, kind, name: id, position, muted: false, hidden: false, locked: false, solo: false, duck: false, clips, ...extra } as unknown as Track;
}

function sequenceWith(tracks: Track[], extra: Partial<Sequence> = {}): Sequence {
  return {
    id: "s1",
    name: "S",
    project_id: project.id,
    workspace_id: workspace.id,
    width: 1920,
    height: 1080,
    fps: 30,
    revision: 1,
    can_undo: true,
    can_redo: false,
    tracks,
    ...extra,
  } as unknown as Sequence;
}

let current: Sequence;

/** 编辑请求的第一个参数是「照着哪一版做」(SequenceRef):这条时间线的 id 加版本号。 */
const onS1 = expect.objectContaining({ id: "s1" });

function renderEditor(sequence: Sequence) {
  current = sequence;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RecordingProvider workspaceId={workspace.id}>
          <EditorView workspace={workspace} project={project} onCreateProject={vi.fn()} creatingProject={false} />
        </RecordingProvider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { ...utils, client };
}

async function ready() {
  await screen.findByTestId("timeline");
}

function press(key: string, init: KeyboardEventInit = {}) {
  fireEvent.keyDown(document.body, { key, code: key.length === 1 ? `Key${key.toUpperCase()}` : key, ...init });
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  Element.prototype.scrollIntoView = vi.fn();
  mocks.timelineProps = null;
  mocks.monitorProps = null;
  mocks.transcriptProps = null;
  mocks.panelTab = "media";
  for (const fn of Object.values(toasts)) fn.mockReset();
  mocks.api.mockReset().mockImplementation((path: string) => {
    if (path.startsWith("/api/projects/") && path.endsWith("/sequences")) return Promise.resolve([current]);
    return Promise.resolve([]);
  });
  mocks.listFonts.mockReset().mockResolvedValue([]);
  for (const fn of [
    mocks.splitClip, mocks.undoSequence, mocks.redoSequence, mocks.moveClip, mocks.moveClipsBatch, mocks.trimClip,
    mocks.setClipTransform, mocks.splitClipAtPointsBatch, mocks.addTrack,
  ]) {
    fn.mockReset().mockImplementation(async () => current);
  }
  useEditorStore.setState({ playhead: 0, playing: false, selectedClipIds: [], dragDraft: null, tool: "select" });
});

describe("S 键切分", () => {
  it("2 倍速片段在播放头所在的源时刻切开,而不是少乘一个速度", async () => {
    // 时间线 10–20s,源 0–20s:播放头 15s 对应源 10s。
    renderEditor(sequenceWith([track("v1", "video", 0, [clip("c1", "v1", 10, 0, 20, { speed: 2 })])]));
    await ready();
    act(() => useEditorStore.getState().setPlayhead(15));
    press("s");
    await waitFor(() => expect(mocks.splitClip).toHaveBeenCalledTimes(1));
    expect(mocks.splitClip).toHaveBeenCalledWith(onS1, "c1", 10);
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((ok, fail) => {
    resolve = ok;
    reject = fail;
  });
  return { promise, resolve, reject };
}

describe("同一条时间线的编辑排队执行", () => {
  it("连按两次 ⌘Z:第二次等第一次落地再发,不和它撞车", async () => {
    renderEditor(sequenceWith([track("v1", "video", 0, [clip("c1", "v1", 0, 0, 10)])]));
    await ready();
    const first = deferred<Sequence>();
    mocks.undoSequence.mockImplementationOnce(() => first.promise);
    press("z", { metaKey: true });
    press("z", { metaKey: true });
    await waitFor(() => expect(mocks.undoSequence).toHaveBeenCalledTimes(1));
    // 第一次还在路上:第二次不能先发出去。
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(mocks.undoSequence).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve({ ...current, revision: 2 }));
    await waitFor(() => expect(mocks.undoSequence).toHaveBeenCalledTimes(2));
    // 剪辑页的 ⌘Z 只撤自己的;第二下报的版本号是第一下落地之后的那一版,不会拿旧版本去撞 409。
    expect(mocks.undoSequence).toHaveBeenNthCalledWith(1, "s1", { expectedRevision: 1, mine: true });
    expect(mocks.undoSequence).toHaveBeenNthCalledWith(2, "s1", { expectedRevision: 2, mine: true });
  });

  it("连按两次 S:第二刀按第一刀落地后的时间线找片段,不拿已经被切开的旧片段去切", async () => {
    const before = sequenceWith([track("v1", "video", 0, [clip("c1", "v1", 0, 0, 10)])]);
    const after = sequenceWith(
      [track("v1", "video", 0, [clip("c1", "v1", 0, 0, 5), clip("c2", "v1", 5, 5, 10)])],
      { revision: 2 },
    );
    renderEditor(before);
    await ready();
    const first = deferred<Sequence>();
    mocks.splitClip.mockImplementationOnce(() => first.promise);
    act(() => useEditorStore.getState().setPlayhead(5));
    press("s");
    await waitFor(() => expect(mocks.splitClip).toHaveBeenCalledTimes(1));
    act(() => useEditorStore.getState().setPlayhead(7));
    press("s");
    current = after;
    await act(async () => first.resolve(after));
    await waitFor(() => expect(mocks.splitClip).toHaveBeenCalledTimes(2));
    expect(mocks.splitClip).toHaveBeenNthCalledWith(1, onS1, "c1", 5);
    expect(mocks.splitClip).toHaveBeenNthCalledWith(2, onS1, "c2", 7);
  });
});

describe("方向键逐帧", () => {
  it("按帧号加减:停在两帧之间时先落到最近的帧,不把 1/fps 浮点累加上去", async () => {
    renderEditor(sequenceWith([track("v1", "video", 0, [clip("c1", "v1", 0, 0, 20)])]));
    await ready();
    act(() => useEditorStore.getState().setPlayhead(0.51));
    press("ArrowRight");
    expect(useEditorStore.getState().playhead).toBe(16 / 30);
    press("ArrowRight", { shiftKey: true });
    expect(useEditorStore.getState().playhead).toBe(26 / 30);
    press("ArrowLeft");
    expect(useEditorStore.getState().playhead).toBe(25 / 30);
  });
});

/** 时间线把回调交给 EditorView;测试像时间线那样调用它们。 */
function timeline<K extends string>(name: K): (...args: unknown[]) => unknown {
  return mocks.timelineProps![name] as (...args: unknown[]) => unknown;
}

describe("拖动类编辑失败时说出来", () => {
  const seq = () => sequenceWith([track("v1", "video", 0, [clip("c1", "v1", 0, 0, 10)])]);

  it("移动失败:提示原因,草稿撤掉让片段回到原位", async () => {
    renderEditor(seq());
    await ready();
    mocks.moveClip.mockRejectedValueOnce(new Error("Track is locked"));
    act(() => {
      useEditorStore.getState().setDragDraft({ clipId: "c1", trackId: "v1", timeline_start: 3, src_in: 0, src_out: 10, kind: "move", settling: true });
      timeline("onMoveClip")("c1", 3, undefined, false);
    });
    await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("Track is locked"));
    expect(useEditorStore.getState().dragDraft).toBeNull();
  });

  it("修剪、组拖、换到新图层、按句切分失败都会提示", async () => {
    mocks.panelTab = "transcript";
    renderEditor(seq());
    await ready();
    mocks.trimClip.mockRejectedValueOnce(new Error("trim failed"));
    mocks.moveClipsBatch.mockRejectedValueOnce(new Error("batch failed"));
    mocks.addTrack.mockRejectedValueOnce(new Error("layer failed"));
    mocks.splitClipAtPointsBatch.mockRejectedValueOnce(new Error("points failed"));
    act(() => {
      timeline("onTrimClip")("c1", { timeline_start: 0, src_in: 0, src_out: 5 });
      timeline("onMoveClips")([{ clipId: "c1", timelineStart: 2 }]);
      timeline("onMoveClipToNewLayer")("c1", 1);
      (mocks.transcriptProps!.onSplitPoints as (cuts: unknown) => void)([{ clipId: "c1", srcTimes: [2] }]);
    });
    await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("points failed"));
    expect(toasts.error).toHaveBeenCalledWith("layer failed");
    expect(toasts.error).toHaveBeenCalledWith("trim failed");
    expect(toasts.error).toHaveBeenCalledWith("batch failed");
  });

  it("监视器上拖变换失败:提示原因,并告诉监视器这次没成(它好丢掉草稿)", async () => {
    renderEditor(seq());
    await ready();
    mocks.setClipTransform.mockRejectedValueOnce(new Error("transform failed"));
    const result = (mocks.monitorProps!.onSetTransform as (id: string, tf: unknown) => Promise<unknown>)("c1", { scale: 2 });
    await expect(result).rejects.toThrow("transform failed");
    await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("transform failed"));
  });
});
