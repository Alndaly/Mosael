/** @vitest-environment jsdom */
import * as React from "react";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useKeepInCanvas } from "./BoardComposerShell";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

function rect(left: number, width: number, top = 100, height = 40): DOMRect {
  return { left, right: left + width, top, bottom: top + height, width, height, x: left, y: top, toJSON: () => ({}) } as DOMRect;
}

/** 和操作条一样:没选中时照样挂着、只是渲染成空,选中了条才出现。 */
function Bar({ shown }: { shown: boolean }) {
  const bar = React.useRef<HTMLDivElement | null>(null);
  const fit = useKeepInCanvas(bar, { vertical: false });
  if (!shown) return null;
  return <div ref={bar} data-bar="" style={fit} />;
}

describe("面板 / 操作条贴着画布边时平移回来", () => {
  beforeEach(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      disconnect() {}
      unobserve() {}
    } as unknown as typeof ResizeObserver;
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 0;
    });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      //: 画布从 64px 开始(左边是侧栏);条被摆在 45px,左边一截钻到侧栏底下。
      return this.classList.contains("react-flow") ? rect(64, 1000, 0, 800) : rect(45, 330);
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("挂载时还没渲染出来、之后才出现的那一条也会被量、被挪回画布里", () => {
    const { rerender, container } = render(
      <div className="react-flow">
        <Bar shown={false} />
      </div>,
    );
    act(() =>
      rerender(
        <div className="react-flow">
          <Bar shown />
        </div>,
      ),
    );
    const bar = container.querySelector<HTMLElement>("[data-bar]")!;
    //: 64 + 12 的边距(CANVAS_MARGIN) − 45 = 31。
    expect(bar.style.transform).toBe("translateX(31px)");
  });
});
