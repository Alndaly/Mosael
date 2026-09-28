/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 画板上的时间线格(ADR 0030):缩略图条按先后排、宽度跟时长;剪刀切播放头所在的那一段;删掉选中的一段(波纹,不留空当);
 * 拖一段换顺序(首尾相接重排、一次提交);时间线被删了就照实说。每一步都是那条时间线上的正常操作。
 */

const api = vi.hoisted(() => ({
  getSequence: vi.fn(),
  splitClip: vi.fn(),
  rippleDeleteClipsBatch: vi.fn(),
  moveClipsBatch: vi.fn(),
}));
vi.mock("@/api/domains/editor", () => api);
vi.mock("@/api/domains/assets", () => ({ assetFileUrl: (id: string) => `/file/${id}`, assetThumbnailUrl: (id: string) => `/thumb/${id}` }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ApiError } from "@/api/transport";
import { boardSequenceKey, SequenceCell, SequenceToolbarActions, reorderedClips, sequenceSummary, stripLayout } from "./SequenceCell";
import { onSequenceEdit, SequenceAddContext, updateSequenceCursor } from "./sequenceCursor";

const clip = (id: string, start: number, length: number, extra: Record<string, unknown> = {}) => ({
  id, asset_id: `a-${id}`, asset_kind: "video", timeline_start: start, src_in: 0, src_out: length, speed: 1, ...extra,
});
const SEQUENCE = {
  id: "seq", project_id: "proj",
  tracks: [
    { id: "v", kind: "video", position: 0, clips: [clip("b", 4, 2), clip("a", 0, 4)] },
    { id: "m", kind: "audio", position: 1, clips: [clip("music", 0, 6, { asset_kind: "audio" })] },
  ],
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SequenceCell sequenceId="seq" />
      {/* 剪刀、删除、在剪辑里打开在格子上方的操作条上;这里用最简单的按钮代替操作条的样子。 */}
      <SequenceToolbarActions
        sequenceId="seq"
        button={({ label, onClick, disabled, href }) =>
          href !== undefined ? <a key={label} aria-label={label} href={href}>{label}</a>
            : <button key={label} type="button" aria-label={label} disabled={disabled} onClick={onClick}>{label}</button>}
      />
    </QueryClientProvider>,
  );
}

const tile = (id: string) => document.querySelector<HTMLButtonElement>(`[data-sequence-clip="${id}"]`)!;

beforeEach(() => {
  updateSequenceCursor("seq", { time: 0, picked: null });
  for (const fn of Object.values(api)) fn.mockReset();
  api.getSequence.mockResolvedValue(SEQUENCE);
  for (const fn of [api.splitClip, api.rippleDeleteClipsBatch, api.moveClipsBatch]) fn.mockResolvedValue(SEQUENCE);
});

describe("时间线格", () => {
  it("缩略图条按先后排、宽度跟时长(有最小宽度);播放头和点击按每段的实际位置换算", () => {
    const layout = stripLayout([clip("a", 0, 4), clip("b", 4, 1)] as never);
    expect(layout.tiles.map((one) => [one.clip.id, one.x, one.width])).toEqual([["a", 6, 88], ["b", 96, 44]]);
    expect(layout.toX(2)).toBe(6 + 44);
    //: 1 秒的镜头撑到了 44 像素,播放头按它自己的宽度走。
    expect(layout.toX(4.5)).toBe(96 + 22);
    expect(layout.toTime(96 + 22)).toBeCloseTo(4.5);
  });

  it("排好顺序的缩略图;总长算上音频轨;在剪辑里打开点名这一条时间线;格子里不再放工具按钮", async () => {
    mount();
    await waitFor(() => expect(tile("a")).not.toBeNull());
    const order = [...document.querySelectorAll("[data-sequence-clip]")].map((one) => one.getAttribute("data-sequence-clip"));
    expect(order).toEqual(["a", "b"]);
    expect(document.querySelector("[data-sequence-time]")?.textContent).toContain("6.0s");
    expect(screen.getByRole("link", { name: "boardSequenceOpen" }).getAttribute("href")).toBe("#/editor?p=proj&s=seq");
    //: 用户:「这些按钮放到上方弹窗中去」—— 格子里只剩预览和缩略图条。
    const cell = document.querySelector("[data-sequence-cell]")!;
    expect(cell.querySelector('[aria-label="boardSequenceCut"], [aria-label="boardSequenceDelete"], [aria-label="boardSequenceOpen"]')).toBeNull();
  });

  it("剪刀切播放头所在的那一段(按素材里的秒数);播放头在段的边上时没什么可切", async () => {
    mount();
    await waitFor(() => expect(tile("a")).not.toBeNull());
    expect(screen.getByRole("button", { name: "boardSequenceCut" })).toBeDisabled();
    const strip = document.querySelector<HTMLElement>("[data-sequence-strip]")!;
    strip.getBoundingClientRect = () => ({ left: 0, width: 0 } as DOMRect);
    //: 按在条上的空白处 = 拖播放头。
    fireEvent.pointerDown(strip, { clientX: 6 + 22 * 1.5, pointerId: 1 });
    fireEvent.pointerUp(strip, { clientX: 6 + 22 * 1.5, pointerId: 1 });
    const edits: string[] = [];
    const stop = onSequenceEdit((id) => edits.push(id));
    fireEvent.click(screen.getByRole("button", { name: "boardSequenceCut" }));
    await waitFor(() => expect(api.splitClip).toHaveBeenCalled());
    //: 剪成了就告诉画板,记进它的撤销栈(⌘Z 撤得回来)。
    await waitFor(() => expect(edits).toEqual(["seq"]));
    stop();
    expect(api.splitClip.mock.calls[0][0]).toBe("seq");
    expect(api.splitClip.mock.calls[0][1]).toBe("a");
    expect(api.splitClip.mock.calls[0][2]).toBeCloseTo(1.5);
  });

  it("点一段(没拖)就选中它;删掉选中的一段用波纹删(后面的往前补,不留空当)", async () => {
    mount();
    await waitFor(() => expect(tile("b")).not.toBeNull());
    expect(screen.getByRole("button", { name: "boardSequenceDelete" })).toBeDisabled();
    const strip = document.querySelector<HTMLElement>("[data-sequence-strip]")!;
    strip.getBoundingClientRect = () => ({ left: 0, width: 0 } as DOMRect);
    fireEvent.click(tile("b"), { clientX: 110 });
    expect(tile("b").getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "boardSequenceDelete" }));
    await waitFor(() => expect(api.rippleDeleteClipsBatch).toHaveBeenCalledWith("seq", ["b"]));
    expect(api.moveClipsBatch).not.toHaveBeenCalled();
  });

  it("拖一段落到另一段的位置:按新先后首尾相接重排;没挪就不动", () => {
    const [a, b, c] = [clip("a", 0, 4), clip("b", 4, 2), clip("c", 6, 1)] as never[];
    expect(reorderedClips([a, b, c], "c", "a")?.map((one: { id: string }) => one.id)).toEqual(["c", "a", "b"]);
    expect(reorderedClips([a, b, c], "a", "a")).toBeNull();
    expect(reorderedClips([a, b, c], "a", null)).toBeNull();
  });

  it("按住一段横着拖(拖动库 @dnd-kit,不靠浏览器的拖放):拖着时不画播放头,松手重排、一次提交", async () => {
    mount();
    await waitFor(() => expect(tile("b")).not.toBeNull());
    //: jsdom 不排版:照缩略图条的布局给每一段一个位置,拖动库按它们找落点。
    const boxes: Record<string, [number, number]> = { a: [6, 88], b: [96, 44] };
    const original = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function (this: Element) {
      const [left, width] = boxes[this.getAttribute("data-sequence-clip") ?? ""] ?? [0, 0];
      return { left, width, top: 0, height: 60, right: left + width, bottom: 60, x: left, y: 0, toJSON: () => ({}) } as DOMRect;
    };
    try {
      fireEvent.pointerDown(tile("b"), { clientX: 110, clientY: 30, isPrimary: true, button: 0, pointerId: 1 });
      fireEvent.pointerMove(document, { clientX: 60, clientY: 30, pointerId: 1 });
      await waitFor(() => expect(document.querySelector("[data-sequence-playhead]"), "拖的时候不画播放头").toBeNull());
      fireEvent.pointerMove(document, { clientX: 10, clientY: 30, pointerId: 1 });
      fireEvent.pointerUp(document, { clientX: 10, clientY: 30, pointerId: 1 });
      await waitFor(() => expect(api.moveClipsBatch).toHaveBeenCalled());
      expect(api.moveClipsBatch).toHaveBeenCalledWith("seq", [{ clip_id: "b", timeline_start: 0 }, { clip_id: "a", timeline_start: 2 }]);
    } finally {
      Element.prototype.getBoundingClientRect = original;
    }
  });

  it("播放头不是文字:条上不给文本光标,播放头按住左右拖", async () => {
    mount();
    await waitFor(() => expect(tile("a")).not.toBeNull());
    expect(document.querySelector("[data-sequence-strip]")?.className).not.toContain("cursor-text");
    expect(document.querySelector("[data-sequence-playhead]")?.className).toContain("cursor-ew-resize");
  });

  it("播放头有手柄,画在条上", async () => {
    mount();
    await waitFor(() => expect(tile("a")).not.toBeNull());
    expect(document.querySelector("[data-sequence-playhead]")).not.toBeNull();
  });

  it("滚轮交给画布:条上不标 nowheel(触控板双指平移经过这里不能停)", async () => {
    mount();
    await waitFor(() => expect(tile("a")).not.toBeNull());
    expect(document.querySelector("[data-sequence-cell] .nowheel")).toBeNull();
  });

  it("空的时间线说该怎么往里放;时间线被删了照实说", async () => {
    api.getSequence.mockResolvedValue({ ...SEQUENCE, tracks: [{ id: "v", kind: "video", position: 0, clips: [] }] });
    const { unmount } = mount();
    expect(await screen.findByText("boardSequenceEmpty")).toBeTruthy();
    expect(screen.getByText("boardSequenceStripEmpty")).toBeTruthy();
    unmount();
    api.getSequence.mockRejectedValue(new ApiError("Not Found", 404, ""));
    const gone = mount();
    await waitFor(() => expect(document.querySelector("[data-sequence-missing]")).not.toBeNull());
    expect(screen.getByText("boardSequenceMissing")).toBeTruthy();
    gone.unmount();
    //: 别的错(断网、服务端出错)不是「删掉了」—— 说成删了,用户会去把这一格删掉。
    api.getSequence.mockRejectedValue(new ApiError("Internal Server Error", 500, ""));
    mount();
    await waitFor(() => expect(document.querySelector("[data-sequence-load-failed]")).not.toBeNull());
    expect(document.querySelector("[data-sequence-missing]")).toBeNull();
    expect(screen.getByText("boardSequenceLoadFailed")).toBeTruthy();
  });

  it("条末尾的「+」交给画板挑素材(点名这一条时间线);格子单独渲染时没有「+」", async () => {
    mount();
    await waitFor(() => expect(tile("a")).not.toBeNull());
    expect(document.querySelector("[data-sequence-add]")).toBeNull();
    const pick = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SequenceAddContext.Provider value={pick}>
          <SequenceCell sequenceId="seq" />
        </SequenceAddContext.Provider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(document.querySelector("[data-sequence-add]")).not.toBeNull());
    fireEvent.click(document.querySelector("[data-sequence-add]")!);
    expect(pick).toHaveBeenCalledWith("seq");
  });

  it("导出面板上那一行:几段(主视频轨)、多长(算上音频)、画幅", () => {
    expect(sequenceSummary({ ...SEQUENCE, width: 1080, height: 1920 } as never)).toEqual({ clips: 2, seconds: 6, size: "1080×1920" });
    expect(sequenceSummary(undefined)).toEqual({ clips: 0, seconds: 0, size: "" });
  });

  it("缓存挂在 sequences 底下:智能体改了时间线,确认卡执行后刷新 sequences 时它跟着重取", () => {
    expect(boardSequenceKey("seq")[0]).toBe("sequences");
  });
});
