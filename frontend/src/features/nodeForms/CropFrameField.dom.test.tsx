/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", () => ({
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  getAsset: vi.fn(async (id: string) => ({ id, media_info: { width: 1600, height: 900 } })),
}));
vi.mock("@/components/generation/MaskEditor", () => ({
  MaskEditor: ({ open, source, initial, onDone }: {
    open: boolean;
    source: { assetId: string } | null;
    initial: { assetId: string } | null;
    onDone: (asset: { id: string }) => void;
  }) =>
    open ? (
      <div role="dialog" data-source={source?.assetId ?? ""} data-initial={initial?.assetId ?? ""}>
        <button type="button" onClick={() => onDone({ id: "mask-new" })}>save</button>
      </div>
    ) : null,
}));

import { CropFrameField } from "./CropFrameField";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
import { WHOLE } from "./cropFrame";
import { MaskPaintField } from "./MaskPaintField";

const wrap = (node: React.ReactNode) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>
);

describe("裁切框控件(ADR 0110)", () => {
  it("拖右下角改大小,按底板的尺寸换成比例;方向键挪一点", () => {
    const onChange = vi.fn();
    const box = { x: 0.25, y: 0.25, width: 0.5, height: 0.5 };
    const { container } = render(wrap(<CropFrameField box={box} onChange={onChange} />));
    const stage = container.querySelector<HTMLElement>("[data-crop-stage]")!;
    stage.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 300, right: 400, bottom: 300, x: 0, y: 0, toJSON: () => ({}) });
    const corner = container.querySelector<HTMLElement>('[data-crop-handle="se"]')!;
    (corner as unknown as { setPointerCapture: () => void }).setPointerCapture = () => undefined;
    fireEvent.pointerDown(corner, { clientX: 300, clientY: 225, pointerId: 1 });
    fireEvent.pointerMove(stage, { clientX: 340, clientY: 255, pointerId: 1 });
    expect(onChange).toHaveBeenLastCalledWith({ x: 0.25, y: 0.25, width: expect.closeTo(0.6), height: expect.closeTo(0.6) });
    fireEvent.pointerUp(stage, { pointerId: 1 });
    onChange.mockClear();
    fireEvent.pointerMove(stage, { clientX: 10, clientY: 10, pointerId: 1 });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("group", { name: "cropFrameLabel" }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith({ ...box, x: expect.closeTo(0.26) });
  });

  it("点一个比例:按原图的宽高比摆好最大的居中框;读数是切出来的像素", async () => {
    const onChange = vi.fn();
    render(wrap(<CropFrameField imageAssetId="a1" box={WHOLE} onChange={onChange} />));
    expect(await screen.findByText("cropReadout")).toBeTruthy();
    //: 整张图认成「原图」(1600×900 的图上它和 16:9 是同一个框,先认原图)。
    expect(screen.getByRole("button", { name: "cropAspectOriginal" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "1:1" }));
    const square = onChange.mock.lastCall![0];
    expect(square.height).toBe(1);
    expect(square.width).toBeCloseTo(900 / 1600);
    expect(square.x).toBeCloseTo((1 - 900 / 1600) / 2);
  });
});

describe("重绘的蒙版控件(ADR 0110)", () => {
  it("点「画要重绘的地方」打开蒙版编辑器,底图是这一格的图;存好记下新蒙版", () => {
    const onChange = vi.fn();
    render(<MaskPaintField workspaceId="w" imageAssetId="photo" imageName="照片" onChange={onChange} />);
    expect(document.querySelector("[data-mask-overlay]")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /maskPaintDraw/ }));
    const editor = screen.getByRole("dialog");
    expect(editor.dataset.source).toBe("photo");
    expect(editor.dataset.initial).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    expect(onChange).toHaveBeenCalledWith("mask-new");
  });

  it("画过了:原图上压一层蒙版,按钮是「接着画」(接着在那张上画),旁边能清掉", () => {
    const onChange = vi.fn();
    render(<MaskPaintField workspaceId="w" imageAssetId="photo" imageName="照片" maskAssetId="mask-1" onChange={onChange} />);
    expect(document.querySelector("[data-mask-overlay]")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /maskPaintContinue/ }));
    expect(screen.getByRole("dialog").dataset.initial).toBe("mask-1");
    fireEvent.click(screen.getByRole("button", { name: "maskPaintClear" }));
    expect(onChange).toHaveBeenCalledWith("");
  });
});
