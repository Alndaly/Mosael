/** @vitest-environment jsdom */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { CanvasPointPicker } from "./canvasPointPicker";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const options = [{ value: "note", label: "便签" }];

function content(): HTMLElement | null {
  return document.querySelector<HTMLElement>("[data-radix-popper-content-wrapper] > [role='dialog']");
}

/**
 * 用户看到的:单子开着时在画布别处再双击,锚(钉在双击点的零尺寸元素)挪过去了,单子却还挂在上一个点 ——
 * 零尺寸的锚动了,定位库察觉不到,不会重算。jsdom 不排版,这里钉的是「换一个点就换一份单子」:弹层是重新挂上的。
 */
describe("双击空白处的添加单子:换一个双击点,单子跟到新点", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  it("开着时换一个点:弹层重新挂上,锚在新点", () => {
    const props = { options, searchPlaceholder: "添加", onPick: vi.fn(), onClose: vi.fn() };
    const view = render(<CanvasPointPicker at={{ x: 100, y: 100 }} {...props} />);
    const first = content();
    expect(first, "单子没打开").toBeTruthy();

    view.rerender(<CanvasPointPicker at={{ x: 600, y: 300 }} {...props} />);
    const second = content();
    expect(second, "换点后单子没开着").toBeTruthy();
    expect(second).not.toBe(first);
    const anchor = document.querySelector<HTMLElement>("[data-canvas-point-picker]")!;
    expect([anchor.style.left, anchor.style.top]).toEqual(["600px", "300px"]);
  });
});

/**
 * 点浮层**外面**(画布空白)也要能关掉,不只 Esc —— Radix 自带的「点外部关闭」被 React Flow 画布吃掉
 * (画布在 pointerdown 上 stopPropagation、d3 吞 click),修在 ui 浮层层的全局兜底(canvasBlankDismiss):
 * 点在 `.react-flow__pane` 底板上,所有走 ui 外壳的浮层一次都关。这里用假画布演「capture 掐断」,
 * 钉的是「点画布空白 → 这份单子也关」这条路径。
 */
describe("点单子外面(画布空白)关掉", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  function renderOpenPicker(onClose: () => void) {
    return render(
      <>
        {/* 演 React Flow: Pane 在 capture 阶段 stopPropagation(选框),Radix 冒泡阶段的 dismiss 收不到。 */}
        <div data-testid="blank-pane" className="react-flow__pane" onPointerDownCapture={(event) => event.stopPropagation()} />
        <CanvasPointPicker at={{ x: 100, y: 100 }} options={options} searchPlaceholder="添加" onPick={vi.fn()} onClose={onClose} />
      </>,
    );
  }

  it("点在浮层内容里不关、点在浮层外(空白)关", async () => {
    const onClose = vi.fn();
    renderOpenPicker(onClose);
    const panel = content();
    expect(panel, "单子没打开").toBeTruthy();

    // 点在单子浮层内容里:不关
    fireEvent.pointerDown(panel!);
    expect(onClose).not.toHaveBeenCalled();

    // 点在画布空白:关(全局兜底)。Radix 的 document pointerdown 监听是 setTimeout(0) 后挂的,
    // 回调里重发顺带把那个时序等出来(真机上开单子到点画布隔着用户操作,必已就位)。
    const pane = screen.getByTestId("blank-pane");
    await waitFor(() => {
      fireEvent.pointerDown(pane, { button: 0 });
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  it("收起(at=null)时浮层没挂载,点画布空白不关", () => {
    const onClose = vi.fn();
    render(
      <>
        <div data-testid="blank-pane" className="react-flow__pane" />
        <CanvasPointPicker at={null} options={options} searchPlaceholder="添加" onPick={vi.fn()} onClose={onClose} />
      </>,
    );
    fireEvent.pointerDown(screen.getByTestId("blank-pane"));
    expect(onClose).not.toHaveBeenCalled();
  });
});
