/** @vitest-environment jsdom */
/**
 * 时间线上的手势:标尺、拖动、修剪落在哪一刻,以及它们在键盘与指针意外中断时的表现。
 *
 * jsdom 没有版面,画布的 getBoundingClientRect 恒为 0,所以指针的 clientX 就是画布里的像素位置:
 * 在默认 40px/s 下,clientX = 41 指的是 1.025 秒。
 */
import { DndContext } from "@dnd-kit/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import type { Clip, Sequence, Track } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useEditorStore } from "@/features/editor/editorStore";
import { Timeline } from "@/features/editor/timeline/Timeline";

function clip(id: string, trackId: string, start: number, srcIn: number, srcOut: number, extra: Partial<Clip> = {}): Clip {
  return {
    id, track_id: trackId, asset_id: null, asset_kind: "", timeline_start: start, src_in: srcIn, src_out: srcOut,
    speed: 1, gain: 1, muted: false, text_override: id, effects: {}, transform: {}, ...extra,
  } as Clip;
}

function track(id: string, kind: string, position: number, clips: Clip[] = [], extra: Partial<Track> = {}): Track {
  return { id, kind, name: id, position, muted: false, hidden: false, locked: false, solo: false, duck: false, clips, ...extra } as unknown as Track;
}

type Handlers = Partial<React.ComponentProps<typeof Timeline>>;

function renderTimeline(tracks: Track[], handlers: Handlers = {}, fps = 30) {
  const sequence = { id: "s", name: "S", width: 1920, height: 1080, fps, tracks } as unknown as Sequence;
  const props = {
    onInsertClip: vi.fn(),
    onMoveClip: vi.fn(),
    onTrimClip: vi.fn(),
    ...handlers,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <DndContext>
          <Timeline sequence={sequence} assets={[]} {...props} />
        </DndContext>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { ...utils, props };
}

beforeEach(() => {
  useEditorStore.setState({ playhead: 0, playing: false, pxPerSecond: 40, selectedClipIds: [], dragDraft: null, tool: "select", editMode: "overwrite" });
});

describe("标尺", () => {
  it("点在两帧之间,播放头吸到最近的那一帧", () => {
    renderTimeline([track("V1", "video", 0)]);
    fireEvent.pointerDown(screen.getByTestId("timeline-ruler"), { clientX: 41, pointerId: 1, buttons: 1 });
    expect(useEditorStore.getState().playhead).toBe(31 / 30);
    expect(screen.getByTestId("timeline-playhead-readout").textContent).toMatch(/^00:00:01:01/);
  });
});

describe("修剪", () => {
  it("尾边落在帧上(按序列帧率)", () => {
    const { props } = renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 4)])], {}, 25);
    const handle = screen.getByTestId("trim-end-c1");
    fireEvent.pointerDown(handle, { clientX: 160, pointerId: 1, button: 0, buttons: 1 });
    // 81px = 2.025s,25fps 下最近的帧是第 51 帧(2.04s)。
    fireEvent.pointerMove(handle, { clientX: 81, pointerId: 1, buttons: 1 });
    fireEvent.pointerUp(handle, { clientX: 81, pointerId: 1 });
    expect(props.onTrimClip).toHaveBeenCalledWith("c1", { timeline_start: 0, src_in: 0, src_out: 51 / 25 });
  });
});

describe("拖动", () => {
  it("落点吸到帧上", () => {
    const { props } = renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 2)])]);
    const body = screen.getByTestId("clip-c1");
    act(() => {
      fireEvent.pointerDown(body, { clientX: 10, pointerId: 1, button: 0, buttons: 1 });
    });
    // 位移 51px = 1.275s → 第 38.25 帧 → 第 38 帧。
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 61, clientY: 0, buttons: 1 }));
      window.dispatchEvent(new MouseEvent("pointerup", { clientX: 61, clientY: 0 }));
    });
    expect(props.onMoveClip).toHaveBeenCalledWith("c1", 38 / 30, undefined, false, {});
  });
});

describe("复制与剪切的标记", () => {
  it("文字 / 字幕片段也能复制:工具栏的复制键可用,点了交给 onDuplicateClip", () => {
    const onDuplicateClip = vi.fn();
    renderTimeline([track("S1", "subtitle", 0, [clip("c1", "S1", 0, 0, 2)])], { onDuplicateClip });
    act(() => useEditorStore.getState().selectClip("c1"));
    const button = screen.getByRole("button", { name: "duplicateClip" });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onDuplicateClip).toHaveBeenCalledWith("c1");
  });

  it("剪切了还没粘贴的片段在时间线上标出来", () => {
    renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 2), clip("c2", "V1", 3, 0, 1)])]);
    act(() => useEditorStore.getState().setClipboard({ clipIds: ["c1"], cut: true }));
    expect(screen.getByTestId("clip-c1")).toHaveAttribute("data-cut", "true");
    expect(screen.getByTestId("clip-c2")).not.toHaveAttribute("data-cut");
  });
});

describe("入出点在标尺上", () => {
  it("入点到出点之间画一条选区带", () => {
    renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 10)])]);
    expect(screen.queryByTestId("timeline-marked-range")).toBeNull();
    act(() => {
      useEditorStore.getState().setMarkIn(2.5);
      useEditorStore.getState().setMarkOut(6);
    });
    const band = screen.getByTestId("timeline-marked-range");
    expect(band.style.left).toBe("100px");
    expect(band.style.width).toBe("140px");
  });
});

describe("吸附按钮", () => {
  it("名字走文案表(不是写死的 Snap),按下状态跟着全局开关", () => {
    useEditorStore.setState({ snapEnabled: false });
    renderTimeline([track("V1", "video", 0)]);
    const button = screen.getByRole("button", { name: "timelineSnap" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    expect(useEditorStore.getState().snapEnabled).toBe(true);
    expect(button).toHaveAttribute("aria-pressed", "true");
  });
});

/** 在窗口上发指针事件(拖动片段时监听挂在 window 上)。 */
function windowPointer(type: string, init: MouseEventInit) {
  act(() => {
    window.dispatchEvent(new MouseEvent(type, { buttons: 1, ...init }));
  });
}

describe("拖动中的按键", () => {
  const twoVideoTracks = () => [
    track("V1", "video", 0, [clip("c1", "V1", 0, 0, 2)]),
    track("V2", "video", 1, [clip("c2", "V2", 5, 0, 2)]),
  ];

  it("Esc 取消拖动:不提交,片段回到原处", () => {
    const { props } = renderTimeline(twoVideoTracks());
    fireEvent.pointerDown(screen.getByTestId("clip-c1"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    windowPointer("pointermove", { clientX: 90, clientY: 40 });
    expect(useEditorStore.getState().dragDraft).not.toBeNull();
    fireEvent.keyDown(document.body, { key: "Escape", code: "Escape" });
    expect(useEditorStore.getState().dragDraft).toBeNull();
    windowPointer("pointerup", { clientX: 90, clientY: 40 });
    expect(props.onMoveClip).not.toHaveBeenCalled();
  });

  it("指针被系统收回(pointercancel):当作取消,不提交", () => {
    const { props } = renderTimeline(twoVideoTracks());
    fireEvent.pointerDown(screen.getByTestId("clip-c1"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    windowPointer("pointermove", { clientX: 90, clientY: 40 });
    windowPointer("pointercancel", { clientX: 90, clientY: 40 });
    expect(useEditorStore.getState().dragDraft).toBeNull();
    windowPointer("pointerup", { clientX: 90, clientY: 40 });
    expect(props.onMoveClip).not.toHaveBeenCalled();
  });

  it("按住 ⌥ 松手:在落点复制一份,原片段不动", () => {
    const onDuplicateClipsAt = vi.fn();
    const { props } = renderTimeline(twoVideoTracks(), { onDuplicateClipsAt });
    fireEvent.pointerDown(screen.getByTestId("clip-c1"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    // 位移 120px = 3s。
    windowPointer("pointermove", { clientX: 130, clientY: 40, altKey: true });
    windowPointer("pointerup", { clientX: 130, clientY: 40, altKey: true });
    expect(onDuplicateClipsAt).toHaveBeenCalledWith(["c1"], 3, null);
    expect(props.onMoveClip).not.toHaveBeenCalled();
    expect(useEditorStore.getState().dragDraft).toBeNull();
  });

  it("按住 ⇧ 锁轴:横向为主就不换轨,纵向为主就不改时间", () => {
    const { props } = renderTimeline(twoVideoTracks());
    // 第一下:横移 80px、竖移 50px(会落到 V2 那一行)—— 横向为主,锁在原轨。
    fireEvent.pointerDown(screen.getByTestId("clip-c1"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    windowPointer("pointermove", { clientX: 90, clientY: 90, shiftKey: true });
    windowPointer("pointerup", { clientX: 90, clientY: 90, shiftKey: true });
    expect(props.onMoveClip).toHaveBeenLastCalledWith("c1", 2, undefined, false, {});
  });

  it("按住 ⇧ 纵向为主:换轨但时间不变", () => {
    const { props } = renderTimeline(twoVideoTracks());
    fireEvent.pointerDown(screen.getByTestId("clip-c1"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    windowPointer("pointermove", { clientX: 30, clientY: 90, shiftKey: true });
    windowPointer("pointerup", { clientX: 30, clientY: 90, shiftKey: true });
    expect(props.onMoveClip).toHaveBeenLastCalledWith("c1", 0, "V2", false, {});
  });

  it("按住 ⌘ 临时不吸附", () => {
    const { props } = renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 2), clip("c2", "V1", 5, 0, 2)])]);
    fireEvent.pointerDown(screen.getByTestId("clip-c1"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    // 位移 114px ≈ 2.85s(吸到帧是第 86 帧)→ 尾边离 c2 的头(5s)约 5px —— 平时会吸过去(落在 3s)。
    windowPointer("pointermove", { clientX: 124, clientY: 40, metaKey: true });
    windowPointer("pointerup", { clientX: 124, clientY: 40, metaKey: true });
    expect(props.onMoveClip).toHaveBeenLastCalledWith("c1", 86 / 30, undefined, false, {});
    fireEvent.pointerDown(screen.getByTestId("clip-c1"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    windowPointer("pointermove", { clientX: 124, clientY: 40 });
    windowPointer("pointerup", { clientX: 124, clientY: 40 });
    expect(props.onMoveClip).toHaveBeenLastCalledWith("c1", 3, undefined, false, {});
  });
});

describe("修剪中断", () => {
  const one = () => [track("V1", "video", 0, [clip("c1", "V1", 0, 0, 4)])];

  for (const [name, interrupt] of [
    ["Esc", (handle: HTMLElement) => fireEvent.keyDown(handle, { key: "Escape", code: "Escape" })],
    ["pointercancel", (handle: HTMLElement) => fireEvent.pointerCancel(handle, { pointerId: 1 })],
    ["lostpointercapture", (handle: HTMLElement) => fireEvent(handle, new Event("lostpointercapture"))],
  ] as const) {
    it(`${name}:修剪作废,不提交,草稿撤掉`, () => {
      const { props } = renderTimeline(one());
      const handle = screen.getByTestId("trim-end-c1");
      fireEvent.pointerDown(handle, { clientX: 160, pointerId: 1, button: 0, buttons: 1 });
      fireEvent.pointerMove(handle, { clientX: 81, pointerId: 1, buttons: 1 });
      expect(useEditorStore.getState().dragDraft).not.toBeNull();
      interrupt(handle);
      expect(useEditorStore.getState().dragDraft).toBeNull();
      fireEvent.pointerUp(handle, { clientX: 81, pointerId: 1 });
      expect(props.onTrimClip).not.toHaveBeenCalled();
    });
  }
});

describe("缩放", () => {
  /** jsdom 没有版面:给滚动容器一个 800px 宽的视口。 */
  function viewport(width = 800): HTMLElement {
    const scroller = screen.getByTestId("timeline-scroll");
    Object.defineProperty(scroller, "clientWidth", { configurable: true, value: width });
    return scroller;
  }
  const long = () => [track("V1", "video", 0, [clip("c1", "V1", 0, 0, 60)])];

  it("+ / - 放大缩小,播放头停在屏幕上原来的位置", () => {
    renderTimeline(long());
    const scroller = viewport();
    act(() => useEditorStore.getState().setPlayhead(10));
    scroller.scrollLeft = 300; // 播放头在屏幕 x = 400 - 300 = 100
    fireEvent.keyDown(document.body, { key: "=", code: "Equal" });
    const zoomed = useEditorStore.getState().pxPerSecond;
    expect(zoomed).toBeCloseTo(52);
    expect(10 * zoomed - scroller.scrollLeft).toBeCloseTo(100);
    fireEvent.keyDown(document.body, { key: "-", code: "Minus" });
    expect(useEditorStore.getState().pxPerSecond).toBeCloseTo(40);
    expect(10 * 40 - scroller.scrollLeft).toBeCloseTo(100);
  });

  it("工具栏的放大键同样以播放头为锚", () => {
    renderTimeline(long());
    const scroller = viewport();
    act(() => useEditorStore.getState().setPlayhead(20));
    scroller.scrollLeft = 500; // 屏幕 x = 800 - 500 = 300
    fireEvent.click(screen.getByRole("button", { name: "zoomIn" }));
    expect(20 * useEditorStore.getState().pxPerSecond - scroller.scrollLeft).toBeCloseTo(300);
  });

  it("⌘ + 滚轮以指针为锚", () => {
    renderTimeline(long());
    const scroller = viewport();
    scroller.scrollLeft = 200;
    // 指针在屏幕 x = 120 → 时间 (200 + 120) / 40 = 8s。
    fireEvent.wheel(scroller, { deltaY: -100, ctrlKey: true, clientX: 120 });
    expect(8 * useEditorStore.getState().pxPerSecond - scroller.scrollLeft).toBeCloseTo(120);
  });

  it("适配窗口(⇧Z 或工具栏):整条时间线正好铺满视口,回到开头", () => {
    renderTimeline(long());
    const scroller = viewport();
    scroller.scrollLeft = 900;
    fireEvent.keyDown(document.body, { key: "Z", code: "KeyZ", shiftKey: true });
    const fit = useEditorStore.getState().pxPerSecond;
    expect(60 * fit).toBeLessThanOrEqual(800);
    expect(60 * fit).toBeGreaterThan(700);
    expect(scroller.scrollLeft).toBe(0);
    act(() => useEditorStore.getState().setPxPerSecond(200));
    fireEvent.click(screen.getByRole("button", { name: "zoomToFit" }));
    expect(useEditorStore.getState().pxPerSecond).toBeCloseTo(fit);
  });
});

describe("片段键盘可达", () => {
  const two = () => [track("V1", "video", 0, [clip("c1", "V1", 0, 0, 2), clip("c2", "V1", 3, 0, 1)])];

  it("Tab 进时间线只停一站:选中的那段,没选中时是第一段", () => {
    renderTimeline(two());
    expect(screen.getByTestId("clip-c1")).toHaveAttribute("tabindex", "0");
    expect(screen.getByTestId("clip-c2")).toHaveAttribute("tabindex", "-1");
    act(() => useEditorStore.getState().selectClip("c2"));
    expect(screen.getByTestId("clip-c1")).toHaveAttribute("tabindex", "-1");
    expect(screen.getByTestId("clip-c2")).toHaveAttribute("tabindex", "0");
  });

  it("用键盘聚焦到片段上就选中它;鼠标点出来的聚焦不改选中(⇧ 点击取消选中不会被它撤回)", () => {
    renderTimeline(two());
    act(() => screen.getByTestId("clip-c1").focus());
    expect(useEditorStore.getState().selectedClipIds).toEqual(["c1"]);
    act(() => useEditorStore.getState().selectClips(["c1", "c2"]));
    const second = screen.getByTestId("clip-c2");
    fireEvent.pointerDown(second, { clientX: 130, pointerId: 1, button: 0, buttons: 1, shiftKey: true });
    act(() => second.focus());
    expect(useEditorStore.getState().selectedClipIds).toEqual(["c1"]);
  });

  it("要去的那段在视口外(时间线只画视口里的):先滚过去,画出来后焦点跟上", async () => {
    renderTimeline([track("V1", "video", 0, [clip("near", "V1", 0, 0, 2), clip("far", "V1", 500, 0, 2)])]);
    expect(screen.queryByTestId("clip-far")).toBeNull();
    act(() => screen.getByTestId("clip-near").focus());
    act(() => useEditorStore.getState().selectClip("far"));
    const scroller = screen.getByTestId("timeline-scroll");
    expect(scroller.scrollLeft).toBeGreaterThan(10000);
    fireEvent.scroll(scroller);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId("clip-far")));
  });

  it("焦点在片段上时,选中挪到哪焦点跟到哪", () => {
    renderTimeline(two());
    act(() => screen.getByTestId("clip-c1").focus());
    act(() => useEditorStore.getState().selectClip("c2"));
    expect(document.activeElement).toBe(screen.getByTestId("clip-c2"));
  });
});

describe("快捷键帮助", () => {
  it("剪辑快捷键都列在帮助里", async () => {
    renderTimeline([track("V1", "video", 0)]);
    fireEvent.click(screen.getByRole("button", { name: "shortcutsHelp" }));
    const help = await screen.findByRole("dialog");
    for (const hint of [
      "hintShuttle", "hintMarks", "hintRippleTrim", "hintEditPoints", "hintHomeEnd", "hintSelectAll", "hintSplitAll",
      "hintSnapToggle", "hintNudge", "hintSelectMove", "hintClipboard", "hintZoom", "hintEscape", "hintDragModifiers",
    ]) {
      expect(help).toHaveTextContent(hint);
    }
  });
});

describe("轨道顺序", () => {
  // 后端改了 position(上移一条轨、新建视频轨放到最上)之后,回包里轨道数组的先后不一定跟着变 ——
  // 时间线必须按 position 排,和监视器的合成层序(sceneLayersAt 同样按 position)一致。
  const shuffled = () => [
    track("V1", "video", 1, [clip("base", "V1", 0, 0, 2)]),
    track("V2", "video", 0, [clip("top", "V2", 0, 0, 2)]),
  ];

  it("按 position 从上到下画,不按数组先后", () => {
    renderTimeline(shuffled());
    const names = [...document.querySelectorAll(".group\\/label")].map((row) => row.textContent?.match(/V\d/)?.[0]);
    expect(names).toEqual(["V2", "V1"]);
  });

  it("新建的视频轨(后端放在最上:position 0,回包里却排在数组末尾)画在最上面一行", () => {
    renderTimeline([
      track("V1", "video", 1, [clip("base", "V1", 0, 0, 2)]),
      track("A1", "audio", 2),
      track("V2", "video", 0),
    ]);
    const names = [...document.querySelectorAll(".group\\/label")].map((row) => row.textContent?.match(/[VA]\d/)?.[0]);
    expect(names).toEqual(["V2", "V1", "A1"]);
  });

  it("拖到第二行,落到界面上第二行的那条轨", () => {
    const { props } = renderTimeline(shuffled());
    fireEvent.pointerDown(screen.getByTestId("clip-top"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { clientX: 10, clientY: 90, buttons: 1 }));
      window.dispatchEvent(new MouseEvent("pointerup", { clientX: 10, clientY: 90 }));
    });
    expect(props.onMoveClip).toHaveBeenCalledWith("top", 0, "V1", false, {});
  });
});

describe("拖动预览和后端的覆盖 / 链接 / 修剪语义一致", () => {
  it("覆盖模式:拖到别的片段上,被盖住的部分在预览里就挖掉(整段盖住的不画,露出的剩一截)", () => {
    renderTimeline([
      track("V1", "video", 0, [clip("mover", "V1", 0, 0, 2), clip("under", "V1", 5, 0, 4), clip("gone", "V1", 10, 0, 1)]),
    ]);
    fireEvent.pointerDown(screen.getByTestId("clip-mover"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    // 拖到 7–9:盖住 under(5–9)的后半段。
    windowPointer("pointermove", { clientX: 290, clientY: 40, metaKey: true });
    const under = screen.getByTestId("clip-under");
    expect(under.style.left).toBe("200px");
    expect(under.style.width).toBe("80px"); // 5–7
    // 再拖到 9.5–11.5:整段盖住 gone(10–11),under 完整露出来。
    windowPointer("pointermove", { clientX: 390, clientY: 40, metaKey: true });
    expect(screen.queryByTestId("clip-gone")).toBeNull();
    expect(screen.getByTestId("clip-under").style.width).toBe("160px");
    windowPointer("pointerup", { clientX: 390, clientY: 40, metaKey: true });
  });

  it("链接组员(分离出去的声音)跟着画一起挪;松手只交一段,组员由后端跟着动", () => {
    const { props } = renderTimeline([
      track("V1", "video", 0, [clip("picture", "V1", 0, 0, 2, { link_group: "g" } as Partial<Clip>)]),
      track("A1", "audio", 1, [clip("sound", "A1", 0, 0, 2, { link_group: "g" } as Partial<Clip>)]),
    ]);
    fireEvent.pointerDown(screen.getByTestId("clip-picture"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    windowPointer("pointermove", { clientX: 130, clientY: 40, metaKey: true });
    expect(screen.getByTestId("clip-sound").style.transform).toBe("translate3d(120px, 0, 0)");
    windowPointer("pointerup", { clientX: 130, clientY: 40, metaKey: true });
    expect(props.onMoveClip).toHaveBeenCalledWith("picture", 3, undefined, false, {});
  });

  it("修剪拖过邻居:停在邻居的边上(同轨不重叠)", () => {
    const { props } = renderTimeline([track("V1", "video", 0, [clip("c1", "V1", 0, 0, 4), clip("next", "V1", 5, 0, 2)])]);
    const handle = screen.getByTestId("trim-end-c1");
    fireEvent.pointerDown(handle, { clientX: 160, pointerId: 1, button: 0, buttons: 1 });
    fireEvent.pointerMove(handle, { clientX: 400, pointerId: 1, buttons: 1 });
    fireEvent.pointerUp(handle, { clientX: 400, pointerId: 1 });
    expect(props.onTrimClip).toHaveBeenCalledWith("c1", expect.objectContaining({ src_out: 5 }));
  });
});

describe("链接片段:标记与 ⌥ 临时解链", () => {
  const linkedPair = () => [
    track("V1", "video", 0, [clip("picture", "V1", 0, 0, 2, { link_group: "g" } as Partial<Clip>)]),
    track("A1", "audio", 1, [clip("sound", "A1", 0, 0, 2, { link_group: "g" } as Partial<Clip>), clip("music", "A1", 5, 0, 2)]),
  ];

  it("链接组里的片段带链接标记,普通片段没有", () => {
    renderTimeline(linkedPair());
    expect(screen.getByTestId("clip-picture")).toHaveAttribute("data-linked", "true");
    expect(screen.getByTestId("clip-music")).not.toHaveAttribute("data-linked");
  });

  it("⌥ 单击只选这一段(临时解链):接着拖,声音不跟着走,松手交的是 linked:false", () => {
    const { props } = renderTimeline(linkedPair());
    const picture = screen.getByTestId("clip-picture");
    fireEvent.pointerDown(picture, { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1, altKey: true });
    windowPointer("pointerup", { clientX: 10, clientY: 40, altKey: true });
    expect(useEditorStore.getState()).toMatchObject({ selectedClipIds: ["picture"], selectionUnlinked: true });
    expect(props.onMoveClip).not.toHaveBeenCalled();
    fireEvent.pointerDown(picture, { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1 });
    windowPointer("pointermove", { clientX: 130, clientY: 40, metaKey: true });
    expect(screen.getByTestId("clip-sound").style.transform).toBe("");
    windowPointer("pointerup", { clientX: 130, clientY: 40, metaKey: true });
    expect(props.onMoveClip).toHaveBeenCalledWith("picture", 3, undefined, false, { linked: false });
  });

  it("普通单击回到链接选择", () => {
    renderTimeline(linkedPair());
    act(() => useEditorStore.getState().selectClipUnlinked("picture"));
    fireEvent.pointerDown(screen.getByTestId("clip-music"), { clientX: 210, clientY: 90, pointerId: 1, button: 0, buttons: 1 });
    windowPointer("pointerup", { clientX: 210, clientY: 90 });
    expect(useEditorStore.getState().selectionUnlinked).toBe(false);
  });

  it("按住 ⌥ 修剪:只修这一段", () => {
    const { props } = renderTimeline(linkedPair());
    const handle = screen.getByTestId("trim-end-picture");
    fireEvent.pointerDown(handle, { clientX: 80, pointerId: 1, button: 0, buttons: 1, altKey: true });
    fireEvent.pointerMove(handle, { clientX: 60, pointerId: 1, buttons: 1, altKey: true });
    fireEvent.pointerUp(handle, { clientX: 60, pointerId: 1, altKey: true });
    expect(props.onTrimClip).toHaveBeenCalledWith("picture", expect.objectContaining({ src_out: 1.5, linked: false }));
  });

  it("⌥ 轻点一下(指针抖了一点)不会被当成 ⌥ 拖复制", () => {
    const onDuplicateClipsAt = vi.fn();
    renderTimeline(linkedPair(), { onDuplicateClipsAt });
    fireEvent.pointerDown(screen.getByTestId("clip-picture"), { clientX: 10, clientY: 40, pointerId: 1, button: 0, buttons: 1, altKey: true });
    windowPointer("pointermove", { clientX: 11, clientY: 40, altKey: true });
    windowPointer("pointerup", { clientX: 11, clientY: 40, altKey: true });
    expect(onDuplicateClipsAt).not.toHaveBeenCalled();
  });
});
