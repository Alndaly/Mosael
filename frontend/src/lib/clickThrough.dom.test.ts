/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";

import { swallowClickThrough } from "./clickThrough";

/**
 * 下拉用鼠标选中之后,补发的那一次 click 不落到菜单下面的东西上(用户:「弹窗下拉菜单上的点击会穿透到下方视频」)。
 */
describe("下拉选中后的点击穿透", () => {
  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("鼠标抬起之后紧跟着的那一下 click 落在菜单外:吞掉;下一轮的点击照常", async () => {
    const below = document.body.appendChild(document.createElement("video"));
    const clicked = vi.fn();
    below.addEventListener("click", clicked);
    swallowClickThrough({ pointerType: "mouse" }, () => false);
    below.click();
    expect(clicked).not.toHaveBeenCalled();
    below.click();
    expect(clicked, "只吞一次").toHaveBeenCalledTimes(1);
    swallowClickThrough({ pointerType: "mouse" }, () => false);
    await new Promise((resolve) => setTimeout(resolve, 0));
    below.click();
    expect(clicked, "这一轮派发完就摘掉").toHaveBeenCalledTimes(2);
  });

  it("落在菜单里面的不拦;触屏不管(Radix 在 click 上选,拦了就选不中)", () => {
    const item = document.body.appendChild(document.createElement("div"));
    const clicked = vi.fn();
    item.addEventListener("click", clicked);
    swallowClickThrough({ pointerType: "mouse" }, (target) => target === item);
    item.click();
    swallowClickThrough({ pointerType: "touch" }, () => false);
    item.click();
    expect(clicked).toHaveBeenCalledTimes(2);
  });
});
