/** @vitest-environment jsdom */
import * as React from "react";
import { fireEvent, render } from "@testing-library/react";
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
 * (画布拖动画布时在 pointerdown 上 stopPropagation,Radix 的 dismiss 监听收不到),组件自己兜了一条 capture 阶段的。
 */
describe("点单子外面(画布空白)关掉", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  it("点在浮层内容里不关、点在浮层外(空白)关", () => {
    const onClose = vi.fn();
    render(
      <CanvasPointPicker at={{ x: 100, y: 100 }} options={options} searchPlaceholder="添加" onPick={vi.fn()} onClose={onClose} />,
    );
    const panel = content();
    expect(panel, "单子没打开").toBeTruthy();

    // 点在单子浮层内容里:不关
    fireEvent.pointerDown(panel!);
    expect(onClose).not.toHaveBeenCalled();

    // 点在画布空白(document.body,浮层之外):关
    fireEvent.pointerDown(document.body);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("收起(at=null)时不挂监听,点什么都不关", () => {
    const onClose = vi.fn();
    render(
      <CanvasPointPicker at={null} options={options} searchPlaceholder="添加" onPick={vi.fn()} onClose={onClose} />,
    );
    fireEvent.pointerDown(document.body);
    expect(onClose).not.toHaveBeenCalled();
  });
});
