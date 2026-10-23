/**
 * 浮层策略:认出挂着的提示框 / 引导,按声明关掉,幂等。
 *
 * 这些规则的价值在**漏写与写错的代价**:平台弹层不报错,只是把下一步挡住,失败会以"某个无关步骤
 * 超时"的形式出现(2026-10-23 一天三次)。所以这里把"认、关、再确认"和几种边界钉住。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { clearOverlays } = await import("./overlays");
import type { OverlayDriver, OverlayRule } from "./overlays";

function fakeDriver(initial: { texts?: string[]; css?: string[] } = {}) {
  const texts = new Set(initial.texts ?? []);
  const css = new Set(initial.css ?? []);
  const calls = { clickCss: 0, escape: 0, clickText: [] as string[] };
  const driver: OverlayDriver = {
    hasText: vi.fn(async (text: string) => texts.has(text)),
    cssVisible: vi.fn(async (selector: string) => css.has(selector)),
    clickCss: vi.fn(async () => {
      calls.clickCss += 1;
    }),
    pressKey: vi.fn(async (key) => {
      if (key === "Escape") calls.escape += 1;
    }),
  };
  const clickText = vi.fn(async (text: string) => {
    calls.clickText.push(text);
    //: 点掉之后那句话就该消失(平台行为的最简模型)。
    texts.delete(text === "声明原创" ? "笔记完成原创声明后" : "");
  });
  return { driver, clickText, texts, css, calls };
}

describe("clearOverlays", () => {
  it("没有浮层时一次驱动都不点 —— 幂等,不制造多余的点击", async () => {
    const { driver, clickText } = fakeDriver();
    const rules: OverlayRule[] = [{ detect: { text: "提示" }, dismiss: { click: "知道了" } }];

    expect(await clearOverlays(driver, rules, "test", clickText)).toEqual([]);
    expect(clickText).not.toHaveBeenCalled();
    expect(driver.clickCss).not.toHaveBeenCalled();
  });

  it("按声明行动:先勾框、再点按钮 —— 顺序错了那个按钮是禁用的", async () => {
    const { driver, clickText, calls } = fakeDriver({ texts: ["笔记完成原创声明后"] });
    const rules: OverlayRule[] = [
      {
        detect: { text: "笔记完成原创声明后" },
        dismiss: { tick: ".d-modal-mask input[type=checkbox]", click: "声明原创" },
      },
    ];

    const cleared = await clearOverlays(driver, rules, "test", clickText);

    expect(cleared).toEqual(["笔记完成原创声明后"]);
    expect(calls.clickCss).toBe(1);
    //: 勾框必须发生在点按钮**之前**。
    const order = [
      [driver.clickCss as unknown as { mock: { invocationCallOrder: number[] } }],
      [clickText as unknown as { mock: { invocationCallOrder: number[] } }],
    ];
    expect(order[0][0].mock.invocationCallOrder[0]).toBeLessThan(
      order[1][0].mock.invocationCallOrder[0],
    );
  });

  it("选择器认的浮层(新手引导)按 Esc 关,并用选择器确认它没了", async () => {
    const { driver, clickText, css, calls } = fakeDriver({ css: [".shepherd-element"] });
    const rules: OverlayRule[] = [
      {
        detect: { selector: ".shepherd-element" },
        dismiss: { escape: true },
        gone: { selector: ".shepherd-element" },
      },
    ];
    const escape = driver.pressKey as unknown as { mockImplementation: (fn: () => Promise<void>) => void };
    escape.mockImplementation(async () => {
      css.delete(".shepherd-element");
      calls.escape += 1;
    });

    expect(await clearOverlays(driver, rules, "test", clickText)).toEqual([".shepherd-element"]);
    expect(calls.escape).toBe(1);
  });

  it("套着的浮层:关掉一个再认下一个(平台常见:关掉介绍框又冒出提示)", async () => {
    const { driver, clickText, texts } = fakeDriver({ texts: ["第一层", "第二层"] });
    const rules: OverlayRule[] = [
      { detect: { text: "第一层" }, dismiss: { click: "第一层" } },
      { detect: { text: "第二层" }, dismiss: { click: "第二层" } },
    ];
    (driver.hasText as unknown as { mockImplementation: (fn: (t: string) => Promise<boolean>) => void }).mockImplementation(
      async (text: string) => texts.has(text),
    );
    clickText.mockImplementation(async (text: string) => {
      texts.delete(text);
    });

    const cleared = await clearOverlays(driver, rules, "test", clickText);
    expect(cleared).toEqual(expect.arrayContaining(["第一层", "第二层"]));
    expect(texts.size).toBe(0);
  });
});
