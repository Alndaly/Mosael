/** @vitest-environment jsdom */
import { act, fireEvent, render } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

/**
 * 悬浮窗的叠放次序。
 *
 * 判据有四条,每条都对应一个"不这么做就真的用不了"的点:
 *
 * 1. 后浮起来的在上 —— 刚打开就被压在别人下面是说不通的。
 * 2. 点一下就置顶,且要在**捕获阶段**生效:标题栏拖动和缩放手柄都会 stopPropagation,
 *    冒泡监听在那两处收不到事件,而拖动恰恰最常伴随置顶意图。
 * 3. 快捷键只作用于拿到焦点的那个窗口 —— 每个窗口都装了监听,不判焦点就会一起动。
 * 4. 降到最低也不会低于 Z_BASE。掉到页面内容底下的窗口既看不见也点不到,只能靠清
 *    localStorage 找回来。
 */

import { useFloatingPanel } from "@/features/workflows/useFloatingPanel";

function Panel({ id }: { id: string }) {
  const { style, focusProps } = useFloatingPanel({ storageKey: id, floating: true });
  return (
    <div data-testid={id} style={style} {...focusProps}>
      {/* 模拟标题栏:真实的拖动/缩放起手都会 stopPropagation,冒泡阶段的监听收不到 */}
      <div data-testid={`${id}-header`} onPointerDown={(event) => event.stopPropagation()} />
    </div>
  );
}

function DraggablePanel({ id }: { id: string }) {
  const { style, startDrag } = useFloatingPanel({ storageKey: id, floating: true });
  return (
    <div data-testid={id} style={style}>
      <div data-testid={`${id}-header`} onPointerDown={startDrag}>
        <span data-testid={`${id}-drag-region`} />
        <button data-testid={`${id}-button`} type="button">action</button>
      </div>
    </div>
  );
}

/** 整颗都是把手的那种:语音浮标 —— 它本身就是一颗按钮,没有标题栏可拖。 */
function OrbPanel({ id, onTap }: { id: string; onTap: () => void }) {
  const { style, startDrag, wasDragged } = useFloatingPanel({
    storageKey: id,
    floating: true,
    minW: 52,
    minH: 52,
    preferredW: 52,
    preferredH: 52,
    dragAnywhere: true,
  });
  return (
    <div data-testid={id} style={style}>
      {/* **真的 <button>,不是 role="button" 的 div。** 排除规则按标签名匹配,
          用 div 写的话这个测试会绿着通过而线上照样拖不动 —— 那正是原来那个 bug。 */}
      <button
        data-testid={`${id}-orb`}
        type="button"
        onPointerDown={startDrag}
        onClick={() => {
          if (!wasDragged()) onTap();
        }}
      />
      <button data-testid={`${id}-close`} data-no-drag type="button">×</button>
    </div>
  );
}

const z = (view: ReturnType<typeof render>, id: string) =>
  Number((view.getByTestId(id) as HTMLElement).style.zIndex);

const combo = (key: string) => {
  const event = new KeyboardEvent("keydown", { key, metaKey: true, bubbles: true, cancelable: true });
  // 裸 dispatchEvent 不经过 act,状态更新不会在断言前刷进 DOM。
  act(() => {
    window.dispatchEvent(event);
  });
  return event;
};

describe("悬浮窗叠放次序", () => {
  it("后开的在上;点击置顶;快捷键只动拿到焦点的那个", () => {
    const view = render(
      <>
        <Panel id="panel-a" />
        <Panel id="panel-b" />
      </>,
    );

    expect(z(view, "panel-b")).toBeGreaterThan(z(view, "panel-a"));

    // 捕获阶段:即便子节点拦下冒泡,点一下也要置顶
    fireEvent.pointerDown(view.getByTestId("panel-a-header"));
    expect(z(view, "panel-a")).toBeGreaterThan(z(view, "panel-b"));

    // A 拿着焦点,Cmd+[ 把 A 压到最底
    const lower = combo("[");
    expect(lower.defaultPrevented).toBe(true); // 不拦 Chromium 会当成"后退"
    expect(z(view, "panel-a")).toBeLessThan(z(view, "panel-b"));

    // 焦点仍在 A:此时按 ] 应该动的是 A 而不是 B
    combo("]");
    expect(z(view, "panel-a")).toBeGreaterThan(z(view, "panel-b"));

    view.unmount();
  });

  it("压到最底也不会掉到页面内容底下", () => {
    const view = render(
      <>
        <Panel id="low-a" />
        <Panel id="low-b" />
      </>,
    );
    fireEvent.pointerDown(view.getByTestId("low-a-header"));
    combo("[");
    expect(z(view, "low-a")).toBeGreaterThanOrEqual(55);
    view.unmount();
  });
});

describe("悬浮窗标题栏拖动", () => {
  it("从标题栏空白处拖动窗口，但不从内部按钮起拖", () => {
    const view = render(<DraggablePanel id="drag-panel" />);
    const panel = view.getByTestId("drag-panel") as HTMLElement;
    const initialLeft = Number.parseFloat(panel.style.left);
    const initialTop = Number.parseFloat(panel.style.top);

    fireEvent.pointerDown(view.getByTestId("drag-panel-drag-region"), { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(window, { clientX: 60, clientY: 75 });
    fireEvent.pointerUp(window, { clientX: 60, clientY: 75 });

    expect(Number.parseFloat(panel.style.left)).toBe(initialLeft - 40);
    expect(Number.parseFloat(panel.style.top)).toBe(initialTop - 25);

    fireEvent.pointerDown(view.getByTestId("drag-panel-button"), { clientX: 140, clientY: 125 });
    fireEvent.pointerMove(window, { clientX: 190, clientY: 160 });
    fireEvent.pointerUp(window, { clientX: 190, clientY: 160 });

    expect(Number.parseFloat(panel.style.left)).toBe(initialLeft - 40);
    expect(Number.parseFloat(panel.style.top)).toBe(initialTop - 25);
  });
});

/**
 * 整颗都是把手的浮标。
 *
 * 这一段钉的是一个真的发生过的回归:语音浮标整个就是一颗 `<button>`,而上面那条
 * 「标题栏里的控件不该带着窗口跑」把它的**全部表面**都算成了控件 —— 于是它一步也拖不动,
 * 而症状("按住拖没反应")完全看不出根因在一条为别的面板写的排除规则里。
 */
describe("整颗都是把手的浮标", () => {
  it("按在按钮本体上也能拖走", () => {
    const view = render(<OrbPanel id="orb-panel" onTap={() => undefined} />);
    const panel = view.getByTestId("orb-panel") as HTMLElement;
    const left = Number.parseFloat(panel.style.left);
    const top = Number.parseFloat(panel.style.top);

    fireEvent.pointerDown(view.getByTestId("orb-panel-orb"), { clientX: 300, clientY: 300 });
    fireEvent.pointerMove(window, { clientX: 260, clientY: 275 });
    fireEvent.pointerUp(window, { clientX: 260, clientY: 275 });

    expect(Number.parseFloat(panel.style.left)).toBe(left - 40);
    expect(Number.parseFloat(panel.style.top)).toBe(top - 25);
  });

  it("拖完松手不算一次点击，原地按一下才算", () => {
    // 两件事共用一颗:拖完顺带触发一次"开始免提"是最气人的一种 —— 你只是想把它挪开。
    let taps = 0;
    const view = render(<OrbPanel id="tap-panel" onTap={() => (taps += 1)} />);

    fireEvent.pointerDown(view.getByTestId("tap-panel-orb"), { clientX: 300, clientY: 300 });
    fireEvent.pointerMove(window, { clientX: 240, clientY: 300 });
    fireEvent.pointerUp(window, { clientX: 240, clientY: 300 });
    fireEvent.click(view.getByTestId("tap-panel-orb"));
    expect(taps).toBe(0);

    // 手不稳的一两像素不该吃掉一次点击。
    fireEvent.pointerDown(view.getByTestId("tap-panel-orb"), { clientX: 240, clientY: 300 });
    fireEvent.pointerMove(window, { clientX: 241, clientY: 301 });
    fireEvent.pointerUp(window, { clientX: 241, clientY: 301 });
    fireEvent.click(view.getByTestId("tap-panel-orb"));
    expect(taps).toBe(1);

    // 键盘敲回车:没有任何 pointer 事件,读到的必须是"没拖过"。上一次拖动的位移
    // 留着不清的话,拖过一次之后这颗按钮对键盘用户就彻底失效了。
    fireEvent.pointerDown(view.getByTestId("tap-panel-orb"), { clientX: 241, clientY: 301 });
    fireEvent.pointerMove(window, { clientX: 341, clientY: 301 });
    fireEvent.pointerUp(window, { clientX: 341, clientY: 301 });
    fireEvent.click(view.getByTestId("tap-panel-orb"));
    expect(taps).toBe(1);
    fireEvent.click(view.getByTestId("tap-panel-orb"));
    expect(taps).toBe(2);
  });

  it("标了 data-no-drag 的关闭按钮不起拖", () => {
    const view = render(<OrbPanel id="x-panel" onTap={() => undefined} />);
    const panel = view.getByTestId("x-panel") as HTMLElement;
    const left = Number.parseFloat(panel.style.left);

    fireEvent.pointerDown(view.getByTestId("x-panel-close"), { clientX: 300, clientY: 300 });
    fireEvent.pointerMove(window, { clientX: 200, clientY: 300 });
    fireEvent.pointerUp(window, { clientX: 200, clientY: 300 });

    expect(Number.parseFloat(panel.style.left)).toBe(left);
  });
});
