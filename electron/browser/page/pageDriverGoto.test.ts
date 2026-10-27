/**
 * 导航时记下服务器回的状态码(主框架的 did-navigate)。浏览器自动化的「打开网址」据此把 404 / 5xx 当失败,
 * 而 loadURL 自己对错误页照样 resolve(实测 electron 44:404、500、空 body 的 500 都是「加载成功」)。
 */
import { EventEmitter } from "node:events";

import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { PageDriver } = await import("./pageDriver");

type FakePage = EventEmitter & { getURL: () => string; loadURL: (url: string) => Promise<void> };

/** 一个按真实顺序发事件的页面:先 did-navigate(带状态码),loadURL 再 resolve。 */
function pageAnswering(navigations: Array<[string, number, string]>): FakePage {
  const wc = new EventEmitter() as FakePage;
  wc.getURL = () => navigations[navigations.length - 1][0];
  wc.loadURL = async () => {
    for (const [url, status, text] of navigations) wc.emit("did-navigate", {}, url, status, text);
  };
  return wc;
}

describe("导航记下状态码", () => {
  it("错误页照样加载成功,但状态码带回来", async () => {
    const driver = new PageDriver(pageAnswering([["https://example.com/x", 404, "Not Found"]]) as never);
    await expect(driver.goto("https://example.com/x")).resolves.toEqual({
      outcome: "loaded",
      status: 404,
      statusText: "Not Found",
    });
  });

  it("监听跟着这一次导航走,用完摘掉", async () => {
    const wc = pageAnswering([["https://example.com/x", 200, "OK"]]);
    await new PageDriver(wc as never).goto("https://example.com/x");
    expect(wc.listenerCount("did-navigate")).toBe(0);
  });

  it("跳转多次时认最后一次(落地那一页)", async () => {
    const wc = pageAnswering([
      ["https://example.com/login", 200, "OK"],
      ["https://example.com/final", 500, "Internal Server Error"],
    ]);
    await expect(new PageDriver(wc as never).goto("https://example.com/")).resolves.toMatchObject({ status: 500 });
  });
});
