/**
 * 「在框架里」:同一套动作,脚本改在页面里一个同源 iframe 里跑。
 *
 * 脚本经 Electron 的 WebFrameMain.executeJavaScript 送进那个框架,不在页面里 eval —— 框架页的 CSP
 * 没有 unsafe-eval 时,页面里的 eval 会被拦(我们的测试页就是这样);主进程送进去的不受它管。
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { PageDriver } = await import("./pageDriver");
const { ElementMissingError } = await import("./errors");

type Probe = { state: string; tag?: string; src?: string };

/** 主文档回答「框架找到了没有」;子框架里只有 `mine` 那一个认得打上的记号。 */
function pageWithFrames(probe: Probe, frames: Array<{ mine: boolean; answer: unknown }>) {
  const ran: Array<[string, string]> = [];
  const mainFrame = { executeJavaScript: async () => false };
  const children = frames.map((one, index) => ({
    executeJavaScript: async (code: string) => {
      if (code.includes("__mosaelFrameToken ===")) return one.mine;
      ran.push([`frame${index}`, code]);
      return one.answer;
    },
  }));
  const wc = {
    on: () => undefined,
    getURL: () => "https://example.com/outer",
    executeJavaScript: async (code: string) => {
      if (code.includes("__mosaelFrameToken =")) return probe;
      ran.push(["top", code]);
      return "top-answer";
    },
    mainFrame: { ...mainFrame, framesInSubtree: [mainFrame, ...children] },
  };
  return { driver: new PageDriver(wc as never), ran };
}

describe("找框架", () => {
  it("同源框架:找到它在主进程里对应的那一个", async () => {
    const { driver } = pageWithFrames({ state: "ok" }, [{ mine: false, answer: 1 }, { mine: true, answer: 2 }]);
    await expect(driver.locateFrame("#same")).resolves.toMatchObject({ state: "ok" });
  });

  it.each([
    [{ state: "missing" }, { state: "missing" }],
    [{ state: "notFrame", tag: "DIV" }, { state: "notFrame", tag: "DIV" }],
    [{ state: "crossOrigin", src: "https://other.example/x" }, { state: "crossOrigin", src: "https://other.example/x" }],
  ])("框架不在 / 不是框架 / 是跨域的:原样说出来(%j)", async (probe, expected) => {
    const { driver } = pageWithFrames(probe, []);
    await expect(driver.locateFrame("#x")).resolves.toEqual(expected);
  });
});

describe("在框架里跑", () => {
  it("脚本送进那个框架,不在外层页面跑", async () => {
    const { driver, ran } = pageWithFrames({ state: "ok" }, [{ mine: false, answer: 1 }, { mine: true, answer: 42 }]);
    await expect(driver.inFrame("#same").evaluate("6 * 7")).resolves.toBe(42);
    expect(ran).toEqual([["frame1", "6 * 7"]]);
  });

  it("现成的动作(按选择器点击)整个在框架里做", async () => {
    const { driver, ran } = pageWithFrames({ state: "ok" }, [{ mine: true, answer: true }]);
    await driver.inFrame("#same").clickCss("#frame-btn");
    expect(ran.map(([where]) => where)).toEqual(["frame0"]);
    expect(ran[0][1]).toContain("#frame-btn");
  });

  it("原来那个驱动不受影响:还在外层页面跑", async () => {
    const { driver, ran } = pageWithFrames({ state: "ok" }, [{ mine: true, answer: 1 }]);
    driver.inFrame("#same");
    await expect(driver.evaluate("1")).resolves.toBe("top-answer");
    expect(ran).toEqual([["top", "1"]]);
  });

  it("框架不见了(还没挂出来 / 被换掉了):当成「元素还没出现」,点击和输入会接着等", async () => {
    const { driver } = pageWithFrames({ state: "missing" }, []);
    await expect(driver.inFrame("#late").evaluate("1")).rejects.toBeInstanceOf(ElementMissingError);
  });
});
