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
