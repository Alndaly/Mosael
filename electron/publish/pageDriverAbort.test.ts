/**
 * 动作被中止(运行被取消、后端放弃了这条动作)时,页面驱动要**当场**放手。
 *
 * 实测(2026-10,真实执行器):取消一条正在跑 60 秒脚本的工作流,关闭会话的那一步要等脚本自己跑完才轮得到 ——
 * 同一会话的动作串行,而 executeJavaScript 不认中止开关。那 54 秒里面板一直挂着、页面里的脚本照跑。
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { PageDriver } = await import("./pageDriver");
const { ActionAbortedError } = await import("./errors");

/** 一个永远算不完的页面:executeJavaScript / loadURL 都不 resolve。 */
function stuckWebContents() {
  return {
    on: () => undefined,
    removeListener: () => undefined,
    executeJavaScript: () => new Promise(() => undefined),
    loadURL: () => new Promise(() => undefined),
    getURL: () => "https://example.com/",
  } as never;
}

describe("页面驱动认中止开关", () => {
  it("脚本还在跑时被中止:evaluate 当场抛 ActionAbortedError,不等它跑完", async () => {
    const driver = new PageDriver(stuckWebContents());
    const controller = new AbortController();
    driver.setAbortSignal(controller.signal);
    const started = Date.now();
    const pending = driver.evaluate("new Promise(() => {})", 60_000);
    setTimeout(() => controller.abort(), 20);
    await expect(pending).rejects.toBeInstanceOf(ActionAbortedError);
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it("导航还没完时被中止:goto 也当场放手", async () => {
    const driver = new PageDriver(stuckWebContents());
    const controller = new AbortController();
    driver.setAbortSignal(controller.signal);
    const pending = driver.goto("https://example.com/slow");
    setTimeout(() => controller.abort(), 20);
    await expect(pending).rejects.toBeInstanceOf(ActionAbortedError);
  });

  it("开关早就扳下了:一开始就抛,不碰页面", async () => {
    const executeJavaScript = vi.fn(() => Promise.resolve(1));
    const driver = new PageDriver({ on: () => undefined, executeJavaScript } as never);
    const controller = new AbortController();
    controller.abort();
    driver.setAbortSignal(controller.signal);
    await expect(driver.evaluate("1")).rejects.toBeInstanceOf(ActionAbortedError);
    expect(executeJavaScript).not.toHaveBeenCalled();
  });

  it("没有中止开关时照常跑完", async () => {
    const driver = new PageDriver({ on: () => undefined, executeJavaScript: () => Promise.resolve(7) } as never);
    await expect(driver.evaluate("7")).resolves.toBe(7);
  });

  it("超过预算:抛带着预算的 EvaluateTimeoutError(调用方据此说「跑了多久」)", async () => {
    const { EvaluateTimeoutError } = await import("./errors");
    const driver = new PageDriver(stuckWebContents());
    const error = await driver.evaluate("x", 250).then(() => null, (e: unknown) => e);
    expect(error).toBeInstanceOf(EvaluateTimeoutError);
    expect((error as InstanceType<typeof EvaluateTimeoutError>).budgetMs).toBe(250);
  });
});
