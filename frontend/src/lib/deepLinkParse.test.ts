import { describe, expect, it } from "vitest";

// 被测的是 Electron 主进程那份解析器。它是纯函数、没有 electron 依赖,所以能直接在这里测。
// 放在前端测试里,是因为仓库只有这一套 vitest;逻辑归属仍是 electron/system/deepLink.ts。
import { deepLinkFromArgv, parseDeepLink } from "../../../electron/system/deepLink";

describe("mosael:// 深链解析", () => {
  it("接受白名单内的 view", () => {
    expect(parseDeepLink("mosael://open?view=workflows")).toEqual({ view: "workflows" });
    expect(parseDeepLink("mosael://open?view=publish&id=abc123")).toEqual({ view: "publish", id: "abc123" });
  });

  it("拒绝不在白名单里的 view —— 否则等于把任意字符串塞进 location.hash", () => {
    expect(parseDeepLink("mosael://open?view=../../etc/passwd")).toBeNull();
    expect(parseDeepLink("mosael://open?view=")).toBeNull();
    expect(parseDeepLink("mosael://open")).toBeNull();
  });

  it("只认 open 这一个动作:执行类动作一律不解析", () => {
    // 这是这个模块最重要的一条。协议不需要用户确认就能被任意网页触发,一旦支持
    // 「运行工作流」,访问一个恶意网页就等于让它驱动你的自动化(带着登录态和发布权限)。
    expect(parseDeepLink("mosael://run?view=workflows&id=abc")).toBeNull();
    expect(parseDeepLink("mosael://execute?workflow=abc")).toBeNull();
    expect(parseDeepLink("mosael://publish?id=abc")).toBeNull();
  });

  it("拒绝别的协议", () => {
    expect(parseDeepLink("openstudio://open?view=workflows&id=legacy1")).toBeNull();
    expect(parseDeepLink("https://evil.example/open?view=workflows")).toBeNull();
    expect(parseDeepLink("file:///etc/passwd")).toBeNull();
  });

  it("id 限死字符集", () => {
    expect(parseDeepLink("mosael://open?view=publish&id=has spaces")).toBeNull();
    expect(parseDeepLink("mosael://open?view=publish&id=../../x")).toBeNull();
    expect(parseDeepLink(`mosael://open?view=publish&id=${"a".repeat(65)}`)).toBeNull();
    expect(parseDeepLink(`mosael://open?view=publish&id=${"a".repeat(64)}`)).toEqual({
      view: "publish",
      id: "a".repeat(64),
    });
  });

  it("垃圾输入返回 null 而不是抛 —— 输入来自外部,不该让主进程崩", () => {
    expect(parseDeepLink("")).toBeNull();
    expect(parseDeepLink("not a url")).toBeNull();
    expect(parseDeepLink(undefined as unknown as string)).toBeNull();
    expect(parseDeepLink(123 as unknown as string)).toBeNull();
  });

  it("从 argv 里挑出深链(Windows/Linux 的唤起方式)", () => {
    expect(deepLinkFromArgv(["C:\\app.exe", "--flag", "mosael://open?view=kb"])).toEqual({ view: "kb" });
    expect(deepLinkFromArgv(["C:\\app.exe", "openstudio://open?view=kb"])).toBeNull();
    expect(deepLinkFromArgv(["C:\\app.exe", "--flag"])).toBeNull();
    // 混着一个不合法的和一个合法的:取合法的那个,不因为前一个失败就放弃。
    expect(deepLinkFromArgv(["app", "mosael://run?x=1", "mosael://open?view=media"])).toEqual({
      view: "media",
    });
  });
});
