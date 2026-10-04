import { runInNewContext } from "node:vm";

import { afterEach, describe, expect, it } from "vitest";

import { executeBrowserAction } from "./browserActions";
import { ActionAbortedError, ElementMissingError, EvaluateTimeoutError } from "./errors";
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

  it("服务器回了 404:默认算失败,说出状态码和网址,并提示「允许错误页」", async () => {
    // 实测(真实执行器):打开一个 500 页,节点「成功」,下一步在那张错误页上找元素。
    const driver = fakeDriver("https://example.com/gone", {
      goto: async () => ({ outcome: "loaded" as const, status: 404, statusText: "Not Found" }),
    });
    setLocale("zh-CN");
    const error = await executeBrowserAction(driver, "navigate", { url: "https://example.com/gone" }).then(
      () => null,
      (e: Error) => e,
    );
    expect(error?.message).toMatch(/404.*https:\/\/example\.com\/gone/s);
    expect(error?.message).toContain("允许错误页");
  });

  it("5xx 一样;英文界面说英文", async () => {
    const driver = fakeDriver("https://example.com/", {
      goto: async () => ({ outcome: "loaded" as const, status: 503, statusText: "Service Unavailable" }),
    });
    setLocale("en-US");
    await expect(executeBrowserAction(driver, "navigate", { url: "https://example.com/" })).rejects.toThrow(
      /^The page opened, but the server answered 503 Service Unavailable: https:\/\/example\.com\//,
    );
  });

  it("打开了「允许错误页」:照旧往下走,状态码交出去", async () => {
    const driver = fakeDriver("https://example.com/gone", {
      goto: async () => ({ outcome: "loaded" as const, status: 404, statusText: "Not Found" }),
    });
    await expect(
      executeBrowserAction(driver, "navigate", { url: "https://example.com/gone", allow_error_page: true }),
    ).resolves.toEqual({ value: 404, lastUrl: "https://example.com/gone" });
  });

  it("正常的页面也把状态码交出去;3xx 跳转之后看的是落地那一页", async () => {
    const driver = fakeDriver("https://example.com/", {
      goto: async () => ({ outcome: "loaded" as const, status: 200, statusText: "OK" }),
    });
    await expect(executeBrowserAction(driver, "navigate", { url: "https://example.com/" })).resolves.toEqual({
      value: 200,
      lastUrl: "https://example.com/",
    });
  });

  it("等满 45 秒放行的那种(还在加载)也看状态码", async () => {
    const driver = fakeDriver("https://example.com/slow", {
      goto: async () => ({ outcome: "timeout" as const, status: 500, statusText: "Internal Server Error" }),
    });
    setLocale("zh-CN");
    await expect(executeBrowserAction(driver, "navigate", { url: "https://example.com/slow" })).rejects.toThrow(/500/);
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

/**
 * 照 Electron 的 executeJavaScript 实测的样子(2026-10,electron 44)跑脚本:同步抛错 / 语法错只回一句
 * 「Script failed to execute…去看渲染进程的控制台」,脚本交回的 promise 被拒时原话带回来。
 */
const ELECTRON_SYNC_FAILURE =
  "Script failed to execute, this normally means an error was thrown. Check the renderer console for the error.";
async function electronLikeEvaluate(code: string): Promise<unknown> {
  let completion: unknown;
  try {
    completion = runInNewContext(code);
  } catch {
    throw new Error(ELECTRON_SYNC_FAILURE);
  }
  try {
    return await completion;
  } catch (reason) {
    // 被拒的 promise:Electron 交回的是主进程里的一个 Error,消息是页面那边的原话。
    const message = (reason as { message?: unknown } | null)?.message;
    if (typeof message === "string") throw new Error(message);
    throw reason;
  }
}

describe("执行脚本出错时说出脚本自己的那句话", () => {
  it("同步抛错:错误里是脚本抛的原话,不是「去看渲染进程的控制台」", async () => {
    // 实测:工作流里一个 `throw new Error('…')` 的脚本,节点上只看得到那句英文 —— 用户既看不到那个控制台,
    // 也不知道是哪句话错了。
    const driver = fakeDriver("https://example.com/", { evaluate: electronLikeEvaluate as PageDriver["evaluate"] });
    setLocale("zh-CN");
    const error = await executeBrowserAction(driver, "evaluate", { expression: "throw new Error('故意抛的错 xyz')", input: {} })
      .then(() => null, (e: Error) => e);
    expect(error?.message).toMatch(/脚本运行出错.*故意抛的错 xyz/s);
    expect(error?.message).not.toContain("renderer console");
  });

  it("读了不存在的东西(TypeError)也带上类型和原话", async () => {
    const driver = fakeDriver("https://example.com/", { evaluate: electronLikeEvaluate as PageDriver["evaluate"] });
    setLocale("en-US");
    await expect(
      executeBrowserAction(driver, "evaluate", { expression: "const el = null;\nel.textContent", input: {} }),
    ).rejects.toThrow(/^The script failed: TypeError: Cannot read properties of null/);
  });

  it("语法错误在交给页面之前就说清是语法错", async () => {
    const seen: string[] = [];
    const driver = fakeDriver("https://example.com/", {
      evaluate: (async (code: string) => {
        seen.push(code);
        return electronLikeEvaluate(code);
      }) as PageDriver["evaluate"],
    });
    setLocale("zh-CN");
    await expect(executeBrowserAction(driver, "evaluate", { expression: "this is not js", input: {} })).rejects.toThrow(
      /脚本有语法错误/,
    );
    expect(seen).toEqual([]);
  });

  it("包了一层之后结果照旧:最后一句的值、异步脚本的值、自己声明的 input", async () => {
    const driver = fakeDriver("https://example.com/", { evaluate: electronLikeEvaluate as PageDriver["evaluate"] });
    await expect(
      executeBrowserAction(driver, "evaluate", { expression: "const a = input.n;\na * 2", input: { n: 21 } }),
    ).resolves.toMatchObject({ value: 42 });
    await expect(
      executeBrowserAction(driver, "evaluate", { expression: "(async () => input.w + '!')()", input: { w: "hi" } }),
    ).resolves.toMatchObject({ value: "hi!" });
    await expect(
      executeBrowserAction(driver, "evaluate", { expression: "const input = 5; input + 1", input: {} }),
    ).resolves.toMatchObject({ value: 6 });
  });

  it("异步脚本被拒:原话照样带上", async () => {
    const driver = fakeDriver("https://example.com/", { evaluate: electronLikeEvaluate as PageDriver["evaluate"] });
    setLocale("zh-CN");
    await expect(
      executeBrowserAction(driver, "evaluate", { expression: "(async () => { throw new Error('接口回了 412') })()", input: {} }),
    ).rejects.toThrow(/脚本运行出错.*接口回了 412/s);
  });

  it("超过预算:说脚本跑了多久还没完,不是 evaluate timeout (page not settled)", async () => {
    const driver = fakeDriver("https://example.com/", {
      evaluate: (async (_code: string, budget?: number) => {
        throw new EvaluateTimeoutError(budget ?? 20_000);
      }) as PageDriver["evaluate"],
    });
    setLocale("zh-CN");
    const error = await executeBrowserAction(driver, "evaluate", { expression: "1", input: {}, timeout_ms: 3000 })
      .then(() => null, (e: Error) => e);
    expect(error?.message).toMatch(/脚本运行超过 3\.0 秒还没结束/);
    expect(error?.message).not.toContain("page not settled");
  });

  it("中止(运行被停下)原样抛出,不说成脚本出错", async () => {
    const driver = fakeDriver("https://example.com/", {
      evaluate: (async () => {
        throw new ActionAbortedError();
      }) as PageDriver["evaluate"],
    });
    await expect(executeBrowserAction(driver, "evaluate", { expression: "1", input: {} })).rejects.toBeInstanceOf(
      ActionAbortedError,
    );
  });
});

describe("上传:写了选择器就只认这个选择器", () => {
  it("节点上写了选择器:找输入框和塞文件都只认它,不退回「页面上随便哪个文件框」", async () => {
    // 实测:选择器写成 #nofile(页面上没有),节点却「成功」了 —— 文件被塞进了页面上另一个文件框。
    const calls: Array<[string, unknown]> = [];
    const driver = fakeDriver("https://example.com/upload", {
      fileInputAttached: (async (selector: string, _timeout: number, opts?: unknown) => {
        calls.push([selector, opts]);
        return false;
      }) as PageDriver["fileInputAttached"],
      setFiles: (async () => {
        throw new Error("setFiles should not be reached");
      }) as PageDriver["setFiles"],
    });
    setLocale("zh-CN");
    await expect(
      executeBrowserAction(driver, "upload", { selector: "#nofile", path: "/tmp/a.txt", timeout_ms: 10 }),
    ).rejects.toThrow(/文件输入框没有出现.*#nofile/s);
    expect(calls).toEqual([["#nofile", { exact: true }]]);
  });

  it("没写选择器:照旧找页面上(含 shadow DOM 里)的文件框", async () => {
    const calls: Array<[string, unknown]> = [];
    const driver = fakeDriver("https://example.com/upload", {
      fileInputAttached: (async () => true) as PageDriver["fileInputAttached"],
      setFiles: (async (selector: string, _path: string, opts?: unknown) => {
        calls.push([selector, opts]);
      }) as PageDriver["setFiles"],
    });
    await executeBrowserAction(driver, "upload", { path: "/tmp/a.txt" });
    expect(calls).toEqual([['input[type="file"]', { exact: false }]]);
  });
});

describe("在框架里(iframe)操作", () => {
  /** 外层页面 + 一个框架驱动:动作落在哪一个上,看 calls 里记的是谁。 */
  function framed(lookups: Array<Record<string, unknown>>) {
    const calls: string[] = [];
    const inner = fakeDriver("https://example.com/outer", {
      clickCss: async (selector: string) => void calls.push(`inner click ${selector}`),
      fillField: async (selector: string, value: string) => void calls.push(`inner fill ${selector}=${value}`),
      evaluate: (async () => {
        calls.push("inner evaluate");
        return { value: "框架里的文字" };
      }) as PageDriver["evaluate"],
      cssVisible: async (selector: string) => (calls.push(`inner visible ${selector}`), true),
    });
    const outer = fakeDriver("https://example.com/outer", {
      locateFrame: (async () => (lookups.length > 1 ? lookups.shift() : lookups[0])) as unknown as PageDriver["locateFrame"],
      inFrame: ((frame: string) => (calls.push(`enter ${frame}`), inner)) as PageDriver["inFrame"],
      clickCss: async (selector: string) => void calls.push(`outer click ${selector}`),
      evaluate: (async () => (calls.push("outer evaluate"), { value: "外层" })) as PageDriver["evaluate"],
    });
    return { outer, calls };
  }

  it("填了「在框架里」:点击、输入、读取、等待都落在框架里", async () => {
    const { outer, calls } = framed([{ state: "ok" }]);
    await executeBrowserAction(outer, "click", { selector: "#frame-btn", frame: "#same" });
    await executeBrowserAction(outer, "input", { selector: "#frame-input", value: "你好", frame: "#same" });
    await expect(executeBrowserAction(outer, "extract", { selector: "#inframe", frame: "#same" })).resolves.toMatchObject({
      value: "框架里的文字",
    });
    await executeBrowserAction(outer, "wait", { selector: "#frame-late", frame: "#same", timeout_ms: 1000 });
    expect(calls).toEqual([
      "enter #same", "inner click #frame-btn",
      "enter #same", "inner fill #frame-input=你好",
      "enter #same", "inner evaluate",
      "enter #same", "inner visible #frame-late",
    ]);
  });

  it("没填就照旧在外层页面", async () => {
    const { outer, calls } = framed([{ state: "ok" }]);
    await executeBrowserAction(outer, "click", { selector: "#btn" });
    expect(calls).toEqual(["outer click #btn"]);
  });

  it("框架晚一点才挂出来:等到它再动手", async () => {
    const { outer, calls } = framed([{ state: "missing" }, { state: "missing" }, { state: "ok" }]);
    await executeBrowserAction(outer, "click", { selector: "#frame-btn", frame: "#late", wait_ms: 3000 });
    expect(calls).toEqual(["enter #late", "inner click #frame-btn"]);
  });

  it("跨域框架:说清够不到,而且不等满", async () => {
    const { outer } = framed([{ state: "crossOrigin", src: "https://other.example/inner" }]);
    setLocale("zh-CN");
    const started = Date.now();
    await expect(
      executeBrowserAction(outer, "click", { selector: "#x", frame: "#cross", wait_ms: 5000 }),
    ).rejects.toThrow(/#cross.*https:\/\/other\.example\/inner.*跨域/s);
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it("填的不是框架:说清它是什么", async () => {
    const { outer } = framed([{ state: "notFrame", tag: "DIV" }]);
    setLocale("en-US");
    await expect(executeBrowserAction(outer, "extract", { selector: "#x", frame: "#box" })).rejects.toThrow(
      /#box.*<div>.*iframe/s,
    );
  });

  it("框架一直没出现:说的是框架,不是里面的元素", async () => {
    const { outer } = framed([{ state: "missing" }]);
    setLocale("zh-CN");
    await expect(
      executeBrowserAction(outer, "click", { selector: "#frame-btn", frame: "#never", wait_ms: 300 }),
    ).rejects.toThrow(/找不到框架.*#never/s);
  });

  it("上传:框架交给文件框查找,在那个框架的文档里找", async () => {
    const seen: unknown[] = [];
    const { outer } = framed([{ state: "ok" }]);
    Object.assign(outer, {
      fileInputAttached: async (selector: string, _timeout: number, opts: unknown) => (seen.push([selector, opts]), true),
      setFiles: async (selector: string, _path: string, opts: unknown) => void seen.push([selector, opts]),
    });
    await executeBrowserAction(outer, "upload", { selector: "#frame-file", path: "/tmp/a.txt", frame: "#same" });
    expect(seen).toEqual([
      ["#frame-file", { exact: true, frame: "#same" }],
      ["#frame-file", { exact: true, frame: "#same" }],
    ]);
  });
});

describe("evaluate 的脚本预算", () => {
  it("声明了 timeout_ms 就按它给预算(长读脚本用),没声明走缺省", async () => {
    const seen: Array<number | undefined> = [];
    const driver = fakeDriver("https://example.com/", {
      evaluate: async (_expr: string, budget?: number) => {
        seen.push(budget);
        return { ok: true };
      },
    });
    await executeBrowserAction(driver, "evaluate", { expression: "1", input: {}, timeout_ms: 120000 });
    await executeBrowserAction(driver, "evaluate", { expression: "1", input: {} });
    expect(seen).toEqual([120000, undefined]);
  });
});
