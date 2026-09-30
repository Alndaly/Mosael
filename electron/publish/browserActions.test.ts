import { afterEach, describe, expect, it } from "vitest";

import { executeBrowserAction } from "./browserActions";
import { ElementMissingError } from "./errors";
import { DEFAULT_LOCALE, setLocale } from "../i18n.cjs";
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

afterEach(() => {
  setLocale(DEFAULT_LOCALE);
});

describe("等待超时要说清等的是什么", () => {
  it("选择器等不到时,把选择器、等了多久、当时停在哪一页都写进错误", async () => {
    // 「等待超时」四个字是站点改版之后最常撞见的那条错误,而它当时什么都不说 ——
    // 得让人回去翻节点配置再猜一遍「是选择器写错了,还是页面根本没跳过去」。
    const driver = fakeDriver("https://example.com/login?next=/inbox");
    setLocale("zh-CN");
    await expect(
      executeBrowserAction(driver, "wait", { selector: "#nope", timeout_ms: 4000 }),
    ).rejects.toThrow(/等待超时\(4\.0s\).*#nope.*https:\/\/example\.com\/login/s);
  });

  it("报错跟着界面语言走:英文界面里是英文", async () => {
    // 这条错误会出现在工作流 / 智能体的执行结果里,英文界面里冒出一句中文就是没翻。
    const driver = fakeDriver("https://example.com/login?next=/inbox");
    setLocale("en-US");
    await expect(
      executeBrowserAction(driver, "wait", { selector: "#nope", timeout_ms: 4000 }),
    ).rejects.toThrow(/^Timed out after 4\.0s: the element never appeared: #nope; the page is at https:\/\/example\.com\/login/);
    await expect(executeBrowserAction(driver, "fly", {})).rejects.toThrow("Unknown browser action: fly");
  });

  it("等「消失」和等「出现」说的不是同一件事", async () => {
    const driver = fakeDriver("https://example.com/");
    setLocale("zh-CN");
    await expect(
      executeBrowserAction(driver, "wait", { selector: ".spinner", gone: true, timeout_ms: 1000 }),
    ).rejects.toThrow(/元素始终没有消失.*\.spinner/s);
  });

  it("等网址和等文字也各自说清等的是哪一个", async () => {
    const driver = fakeDriver("https://example.com/still-here");
    setLocale("zh-CN");
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

describe("导航没打开就说没打开", () => {
  it("loadURL 失败(域名解析不了)报导航失败,带错误码和网址", async () => {
    // 此前 reject 只记一行日志,节点照样「成功」,下一步在一张错误页上找元素、报「找不到」。
    const driver = fakeDriver("about:blank", {
      goto: async () => ({ outcome: "rejected" as const, errno: -105, code: "ERR_NAME_NOT_RESOLVED" }),
    });
    setLocale("zh-CN");
    await expect(executeBrowserAction(driver, "navigate", { url: "https://nope.invalid/" })).rejects.toThrow(
      /网页没有打开\(ERR_NAME_NOT_RESOLVED\).*https:\/\/nope\.invalid/s,
    );
  });

  it("ERR_ABORTED(单页应用加载途中自己跳走)放行", async () => {
    const driver = fakeDriver("https://example.com/login", {
      goto: async () => ({ outcome: "rejected" as const, errno: -3, code: "ERR_ABORTED" }),
    });
    await expect(executeBrowserAction(driver, "navigate", { url: "https://example.com/" })).resolves.toEqual({
      lastUrl: "https://example.com/login",
    });
  });

  it("最后停在 chrome-error:// 也算没打开", async () => {
    const driver = fakeDriver("chrome-error://chromewebdata/", { goto: async () => ({ outcome: "loaded" as const }) });
    setLocale("en-US");
    await expect(executeBrowserAction(driver, "navigate", { url: "https://example.com/" })).rejects.toThrow(
      /^The page didn't open \(chrome-error\): https:\/\/example\.com\//,
    );
  });
});

describe("点击和输入先等元素出现", () => {
  it("元素晚一点才挂出来,点击等到它再点", async () => {
    let tries = 0;
    const driver = fakeDriver("https://example.com/", {
      clickCss: async (selector: string) => {
        tries += 1;
        if (tries < 3) throw new ElementMissingError(selector, `clickCss: element not found: ${selector}`);
      },
    });
    await expect(executeBrowserAction(driver, "click", { selector: "#late", wait_ms: 5000 })).resolves.toEqual({
      lastUrl: "https://example.com/",
    });
    expect(tries).toBe(3);
  });

  it("等满还找不到:报按界面语言翻好的话,不是 clickCss 那句英文", async () => {
    const driver = fakeDriver("https://example.com/form", {
      fillField: async (selector: string) => {
        throw new ElementMissingError(selector, `fillField: element not found: ${selector}`);
      },
    });
    setLocale("zh-CN");
    const error = await executeBrowserAction(driver, "input", { selector: "#name", value: "x", wait_ms: 0 }).then(
      () => null,
      (e: Error) => e,
    );
    expect(error?.message).toMatch(/找不到要操作的元素.*#name.*https:\/\/example\.com\/form/s);
    expect(error?.message).not.toMatch(/element not found/);
  });

  it("按文字点击同样等", async () => {
    let tries = 0;
    const driver = fakeDriver("https://example.com/", {
      clickByText: async (text: string) => {
        tries += 1;
        if (tries < 2) throw new ElementMissingError(text, "missing");
      },
    });
    await executeBrowserAction(driver, "click", { text: "发布", wait_ms: 2000 });
    expect(tries).toBe(2);
  });

  it("别的错误不重试,原样抛出", async () => {
    let tries = 0;
    const driver = fakeDriver("https://example.com/", {
      clickCss: async () => {
        tries += 1;
        throw new Error("Task was cancelled by user.");
      },
    });
    await expect(executeBrowserAction(driver, "click", { selector: "#x", wait_ms: 2000 })).rejects.toThrow(/cancelled/);
    expect(tries).toBe(1);
  });
});

describe("提取和滚动:选择器没匹配到默认报错", () => {
  it("提取没匹配:报错(带选择器),不是静默交出 null", async () => {
    const driver = fakeDriver("https://example.com/list", { evaluate: async () => ({ missing: true }) });
    setLocale("zh-CN");
    await expect(executeBrowserAction(driver, "extract", { selector: ".price" })).rejects.toThrow(
      /没有匹配的元素可提取.*\.price/s,
    );
  });

  it("打开「找不到时输出空」:单个给 null,全部给空数组", async () => {
    const driver = fakeDriver("https://example.com/list", { evaluate: async () => ({ missing: true }) });
    await expect(executeBrowserAction(driver, "extract", { selector: ".price", allow_missing: true })).resolves.toMatchObject({
      value: null,
    });
    await expect(
      executeBrowserAction(driver, "extract", { selector: ".price", all: true, allow_missing: true }),
    ).resolves.toMatchObject({ value: [] });
  });

  it("匹配到了就交出值(值本身是空串也照交)", async () => {
    const driver = fakeDriver("https://example.com/list", { evaluate: async () => ({ value: "" }) });
    await expect(executeBrowserAction(driver, "extract", { selector: ".price" })).resolves.toMatchObject({ value: "" });
  });

  it("滚动到的元素不存在:报错;打开开关就跳过", async () => {
    const driver = fakeDriver("https://example.com/", { evaluate: async () => false });
    setLocale("zh-CN");
    await expect(executeBrowserAction(driver, "scroll", { selector: "#footer" })).rejects.toThrow(/没有要滚动到的元素.*#footer/s);
    await expect(executeBrowserAction(driver, "scroll", { selector: "#footer", allow_missing: true })).resolves.toEqual({
      lastUrl: "https://example.com/",
    });
  });
});
