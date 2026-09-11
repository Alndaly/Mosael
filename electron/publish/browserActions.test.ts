import { describe, expect, it } from "vitest";

import { executeBrowserAction } from "./browserActions";
import type { PageDriver } from "./pageDriver";

/** 只实现这几个动作用得到的那几项;其余留空,用到就会立刻炸出来。 */
function fakeDriver(url: string, overrides: Partial<PageDriver> = {}): PageDriver {
  return {
    url: () => url,
    cssVisible: async () => false,
    waitForFunction: async () => false,
    waitForUrl: async () => false,
    evaluate: async () => null,
    ...overrides,
  } as unknown as PageDriver;
}

describe("等待超时要说清等的是什么", () => {
  it("选择器等不到时,把选择器、等了多久、当时停在哪一页都写进错误", async () => {
    // 「等待超时」四个字是站点改版之后最常撞见的那条错误,而它当时什么都不说 ——
    // 得让人回去翻节点配置再猜一遍「是选择器写错了,还是页面根本没跳过去」。
    const driver = fakeDriver("https://example.com/login?next=/inbox");
    await expect(
      executeBrowserAction(driver, "wait", { selector: "#nope", timeout_ms: 4000 }),
    ).rejects.toThrow(/等待超时\(4\.0s\).*#nope.*https:\/\/example\.com\/login/s);
  });

  it("等「消失」和等「出现」说的不是同一件事", async () => {
    const driver = fakeDriver("https://example.com/");
    await expect(
      executeBrowserAction(driver, "wait", { selector: ".spinner", gone: true, timeout_ms: 1000 }),
    ).rejects.toThrow(/元素始终没有消失.*\.spinner/s);
  });

  it("等网址和等文字也各自说清等的是哪一个", async () => {
    const driver = fakeDriver("https://example.com/still-here");
    await expect(
      executeBrowserAction(driver, "wait", { url_contains: "/done", timeout_ms: 2000 }),
    ).rejects.toThrow(/网址里一直没有出现.*\/done/s);
    await expect(
      executeBrowserAction(driver, "wait", { text: "上传完成", timeout_ms: 2000 }),
    ).rejects.toThrow(/页面上一直没有出现文字.*上传完成/s);
  });

  it("特别长的选择器要截断,不然错误糊满一屏反而看不清关键那几个字", async () => {
    const driver = fakeDriver("https://example.com/");
    const long = `div.${"a".repeat(300)}`;
    const error = await executeBrowserAction(driver, "wait", { selector: long, timeout_ms: 1000 })
      .then(() => null, (e: Error) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error!.message.length).toBeLessThan(260);
    expect(error!.message).toContain("…");
  });

  it("等到了就不该报错", async () => {
    const driver = fakeDriver("https://example.com/done", { cssVisible: async () => true });
    await expect(
      executeBrowserAction(driver, "wait", { selector: "#ok", timeout_ms: 1000 }),
    ).resolves.toEqual({ lastUrl: "https://example.com/done" });
  });
});
