/** @vitest-environment jsdom */

/**
 * 主题 token → canvas 认得的颜色。
 *
 * jsdom 里没有样式表(一个 token 也读不出来),所以按**平台**打桩:代理真的 `getComputedStyle`,
 * 只把那个 token 换成一个已知值 —— 和 truncate.dom.test.tsx 同一种做法。这里验的是**解析与订阅**
 * 本身(读 token、切主题叫一声、退订);「画布上那一层真的铺了这个颜色」在
 * components/generation/MaskEditor.dom.test.tsx。
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { observeThemeColor, readThemeColor } from "@/lib/themeColor";

const TOKEN = "--destructive";
const LIGHT = "#bd383e";
const DARK = "#f28d96";

/** 代理真的 getComputedStyle,只把 `TOKEN` 那一个属性换成「按 <html> 上的 .dark 给浅 / 深」。 */
function stubToken(): { reads: number } {
  const state = { reads: 0 };
  const real = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element: Element, pseudo?: string | null) => {
    const style = real(element, pseudo);
    return new Proxy(style, {
      get(target, key) {
        if (key === "getPropertyValue") {
          return (property: string) => {
            if (property !== TOKEN) return target.getPropertyValue(property);
            state.reads += 1;
            return document.documentElement.classList.contains("dark") ? DARK : LIGHT;
          };
        }
        const value = Reflect.get(target, key);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
  });
  return state;
}

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.classList.remove("dark");
  delete document.documentElement.dataset.theme;
  delete document.documentElement.dataset.font;
});

describe("读一个主题 token", () => {
  it("拿到的是当前主题那个值;主题一变,同一个 token 读出来是另一个值", () => {
    stubToken();
    expect(readThemeColor(TOKEN)).toBe(LIGHT);
    document.documentElement.classList.add("dark");
    expect(readThemeColor(TOKEN)).toBe(DARK);
  });

  it("token 不存在(改过名、样式表没加载)就是空串 —— 不编一个兜底色出来", () => {
    stubToken();
    expect(readThemeColor("--no-such-token")).toBe("");
  });
});

describe("订阅主题切换", () => {
  it("`<html>` 上的 class / data-theme 一变就叫一声,退订之后不再叫", async () => {
    stubToken();
    const heard = vi.fn();
    const off = observeThemeColor(heard);

    document.documentElement.classList.add("dark");
    await vi.waitFor(() => expect(heard).toHaveBeenCalledTimes(1));

    document.documentElement.dataset.theme = "dark";
    await vi.waitFor(() => expect(heard).toHaveBeenCalledTimes(2));

    off();
    document.documentElement.classList.remove("dark");
    // MutationObserver 是微任务时机 —— 让它跑完(等到的仍是上面那一次:退订之后没有新的)。
    await Promise.resolve();
    await Promise.resolve();
    expect(heard).toHaveBeenCalledTimes(2);
  });

  it("和颜色无关的属性(换字体写的 data-font)不叫 —— 那时白读一次样式", async () => {
    stubToken();
    const heard = vi.fn();
    const off = observeThemeColor(heard);
    document.documentElement.dataset.font = "serif";
    await Promise.resolve();
    await Promise.resolve();
    expect(heard).not.toHaveBeenCalled();
    off();
  });
});
