/** @vitest-environment jsdom */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { Popover, PopoverContent, PopoverTrigger } from "./popover";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

/**
 * 复现并钉住全局 bug:浮层开着时,**点画布空白处关不掉**,只能 Esc。
 *
 * jsdom 里跑不起真 React Flow,所以用一块假画布演真画布对事件做的两件事
 * (核实过 @xyflow/react 12.12.0 + d3-zoom 3.0.0 的源码,行为和这里一致):
 *
 *  - Pane 的 `onPointerDownCapture` 在选框时 `stopPropagation()`(dist/esm/index.js ~1510):
 *    冒泡到 document 的 pointerdown 被掐死;
 *  - d3-zoom 拖动画布后在 window capture 阶段吞掉 click(`nopropagation`,zoom.js mousedowned/mouseupped):
 *    Radix「点外部关闭」的延迟分支等的那个 click 永远不来。
 *
 * 两条路都使 Radix DismissableLayer 挂在 document 冒泡阶段的 dismiss 收不到画布上的点击。
 * 假画布的 capture stopPropagation 单独就足以让**修复前**的用例变红。
 */
function FakeCanvas({ onPanePointerDown }: { onPanePointerDown?: () => void }) {
  return (
    <div
      data-testid="blank-pane"
      className="react-flow__pane"
      // 演 Pane: capture 阶段掐断(选框),修复绝不能在这里 stopPropagation,否则框选/拖画布会破。
      onPointerDownCapture={(event) => event.stopPropagation()}
      // 演 d3-zoom: 吞掉 click。
      onClickCapture={(event) => event.stopPropagation()}
      // 演画布自己的拖动手势: 冒泡阶段的 pointerdown 必须照常收到(没被破坏的证明)。
      onPointerDown={onPanePointerDown}
    >
      {/* 节点/连线是底板里的子元素:点在它们上面不算「空白画布」。 */}
      <div data-testid="fake-node" className="react-flow__node" />
    </div>
  );
}

function Harness({
  onOpenChange,
  paneProps,
}: {
  onOpenChange: (open: boolean) => void;
  paneProps?: { onPanePointerDown?: () => void };
}) {
  return (
    <>
      <FakeCanvas {...paneProps} />
      <Popover open onOpenChange={onOpenChange}>
        <PopoverTrigger asChild>
          <button>打开</button>
        </PopoverTrigger>
        <PopoverContent>浮层内容</PopoverContent>
      </Popover>
    </>
  );
}

function BarePaneWithPopover() {
  return (
    <>
      {/* 不演「capture 掐断」的假画布:只看兜底对原事件做了什么。 */}
      <div data-testid="blank-pane" className="react-flow__pane" />
      <Popover open onOpenChange={vi.fn()}>
        <PopoverTrigger asChild>
          <button>打开</button>
        </PopoverTrigger>
        <PopoverContent>浮层内容</PopoverContent>
      </Popover>
    </>
  );
}

describe("点画布空白处关掉浮层(React Flow 吞事件的全局兜底)", () => {
  beforeAll(() => {
    vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
    Element.prototype.scrollIntoView ??= () => {};
  });

  it("点在 .react-flow__pane 空白上:浮层收到 onOpenChange(false)", async () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);
    expect(screen.getByText("浮层内容"), "浮层没打开").toBeTruthy();

    // Radix 在 setTimeout(0) 之后才挂 document 的 pointerdown 监听(usePointerDownOutside),
    // 真机上从开浮层到点画布隔着用户操作,必已就位;这里在回调里重发,顺带把这个时序等出来。
    const pane = screen.getByTestId("blank-pane");
    await waitFor(() => {
      fireEvent.pointerDown(pane, { button: 0 });
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("点在画布里的节点上:不算空白,兜底不触发", () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);

    fireEvent.pointerDown(screen.getByTestId("fake-node"), { button: 0 });

    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("点在浮层内容里:不关", () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);

    fireEvent.pointerDown(screen.getByText("浮层内容"), { button: 0 });

    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("非主键(右键/中键)点画布空白:不关", () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);

    fireEvent.pointerDown(screen.getByTestId("blank-pane"), { button: 2 });

    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("兜底不破坏画布事件:不 preventDefault、不拦冒泡(拖动画布/框选靠它们)", () => {
    // 这块假画布不演「capture 掐断」——专门看兜底对原事件做了什么。
    render(<BarePaneWithPopover />);
    const onDocumentBubble = vi.fn();
    document.addEventListener("pointerdown", onDocumentBubble);

    const event = fireEvent.pointerDown(screen.getByTestId("blank-pane"), { button: 0 });

    document.removeEventListener("pointerdown", onDocumentBubble);
    expect(event, "pointerdown 被 preventDefault 了 —— 画布交互被破坏").toBe(true);
    expect(onDocumentBubble, "原 pointerdown 没冒泡到 document —— 被兜底拦了").toHaveBeenCalled();
  });
});
