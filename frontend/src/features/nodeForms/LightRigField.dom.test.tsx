/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { DEFAULT_LIGHT, LIGHT_PRESETS } from "./lightRig";
import { kelvinColor, LightRigField } from "./LightRigField";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

describe("打光节点的灯位控件", () => {
  it("方向键微调方向和高度;一键预设把五个数一起摆好", () => {
    const onChange = vi.fn();
    render(<LightRigField light={DEFAULT_LIGHT} onChange={onChange} />);
    const orb = screen.getByRole("group", { name: /lightRigLabel/ });
    fireEvent.keyDown(orb, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith({ azimuth: 320, elevation: 45 });
    fireEvent.keyDown(orb, { key: "ArrowUp" });
    expect(onChange).toHaveBeenLastCalledWith({ azimuth: 315, elevation: 50 });

    fireEvent.click(screen.getByRole("button", { name: "lightPresetGolden" }));
    expect(onChange).toHaveBeenLastCalledWith(LIGHT_PRESETS.find((one) => one.id === "golden")!.light);
  });

  it("两个把手各管一件事,拿着走:方位把手跟着指针绕环,高度把手跟着指针上下", () => {
    const onChange = vi.fn();
    const { container } = render(<LightRigField light={DEFAULT_LIGHT} onChange={onChange} />);
    const svg = container.querySelector("svg")!;
    //: 画布 240×132(和 viewBox 一样大,换算就是 1:1);球心在 (120, 80),半径 64。
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 240, height: 132, right: 240, bottom: 132, x: 0, y: 0, toJSON: () => ({}) });
    (svg as unknown as { setPointerCapture: () => void }).setPointerCapture = () => undefined;

    fireEvent.pointerDown(container.querySelector('[data-light-handle="azimuth"]')!, { clientX: 184, clientY: 80, pointerId: 1 });
    expect(onChange).toHaveBeenLastCalledWith({ azimuth: 90 });
    fireEvent.pointerMove(svg, { clientX: 56, clientY: 80, pointerId: 1 });
    expect(onChange).toHaveBeenLastCalledWith({ azimuth: 270 });
    fireEvent.pointerUp(svg, { pointerId: 1 });

    fireEvent.pointerDown(container.querySelector('[data-light-handle="elevation"]')!, { clientX: 120, clientY: 16, pointerId: 2 });
    expect(onChange).toHaveBeenLastCalledWith({ elevation: 90 });
    //: 松手之后在画布上移动不再改什么。
    fireEvent.pointerUp(svg, { pointerId: 2 });
    onChange.mockClear();
    fireEvent.pointerMove(svg, { clientX: 10, clientY: 10, pointerId: 2 });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("现在这一套正好是某个预设时,那一枚是选中的", () => {
    const rim = LIGHT_PRESETS.find((one) => one.id === "rim")!;
    render(<LightRigField light={rim.light} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "lightPresetRim" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "lightPresetTop" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("光点的颜色跟着色温:低色温偏橙、日光近白、高色温偏蓝", () => {
    expect(kelvinColor(1500)).toBe("rgb(255, 138, 40)");
    expect(kelvinColor(5500)).toBe("rgb(255, 244, 229)");
    expect(kelvinColor(20000)).toBe("rgb(160, 190, 255)");
  });
});
