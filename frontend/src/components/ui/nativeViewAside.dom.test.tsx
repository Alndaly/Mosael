/** @vitest-environment jsdom */

/**
 * 原生网页视图(内嵌浏览器、ComfyUI 工作台)盖在一切 DOM 上:大图开着时请主进程把它挪到窗口外,关掉时放回 —— 不然整窗的
 * 大图只露得出顶栏和侧栏那几条,图被画布盖住(维护者在工作台里点结果缩略图时就是这样)。
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ImagePreviewProvider, useImagePreview } from "@/components/app/image-preview";
import { stepNativeViewAside } from "@/components/ui/nativeViewAside";

function Opener() {
  const { openImagePreview } = useImagePreview();
  return (
    <button type="button" onClick={() => openImagePreview({ src: "preview://a1", title: "PreviewImage #12 · 1/2",
                                                            gallery: [{ src: "preview://a1" }, { src: "preview://a2" }] })}>
      看大图
    </button>
  );
}

let setOverlay: ReturnType<typeof vi.fn>;
beforeEach(() => {
  setOverlay = vi.fn(async (_up: boolean) => undefined);
  vi.stubGlobal("mosaelPublish", { setOverlay });
});
afterEach(() => vi.unstubAllGlobals());

describe("整窗的浮层亮着时,原生网页视图让开", () => {
  it("大图打开 → 视图挪开;关掉 → 放回;焦点回到点开它的那个按钮;大图压在窗口外壳上面、不当拖拽区", async () => {
    render(
      <ImagePreviewProvider>
        <Opener />
      </ImagePreviewProvider>,
    );
    expect(setOverlay).not.toHaveBeenCalled();
    const opener = screen.getByRole("button", { name: "看大图" });
    opener.focus();
    fireEvent.click(opener);
    await waitFor(() => expect(setOverlay).toHaveBeenLastCalledWith(true));
    const viewer = document.querySelector<HTMLElement>(".PhotoView-Portal")!;
    expect(viewer.className, "压过窗口外壳(z-200)和它的说明(z-210)").toMatch(/\bz-\[220\]/);
    expect(viewer.className, "开着时不当拖拽区(关闭键在顶栏那一条上)").toContain("[-webkit-app-region:no-drag]");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(setOverlay).toHaveBeenLastCalledWith(false));
    expect(setOverlay).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });

  it("几处同时要它让开:最后一处收起才放回;放两次只算一次", () => {
    const first = stepNativeViewAside();
    const second = stepNativeViewAside();
    expect(setOverlay.mock.calls).toEqual([[true]]);
    first();
    first();
    expect(setOverlay.mock.calls, "还有一处要它让开").toEqual([[true]]);
    act(() => second());
    expect(setOverlay.mock.calls).toEqual([[true], [false]]);
  });

  it("网页版(没有这座桥):什么都不做", () => {
    vi.stubGlobal("mosaelPublish", undefined);
    const release = stepNativeViewAside();
    release();
    expect(setOverlay).not.toHaveBeenCalled();
  });
});
