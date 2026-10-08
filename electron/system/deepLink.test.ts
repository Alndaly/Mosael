import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// 被测的是 Electron 主进程那份解析器。它是纯函数、没有 electron 依赖,不用替身。
import { ALLOWED_VIEWS, deepLinkFromArgv, parseDeepLink } from "./deepLink";

const studioViews = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../contracts/studio-views.json"), "utf8"),
) as { views: string[] };

describe("深链白名单 = contracts/studio-views.json", () => {
  it("和前端导航、智能体 open_view 认同一组页面", () => {
    expect([...ALLOWED_VIEWS].sort()).toEqual([...studioViews.views].sort());
  });

  it("官网能链到的每一页都唤得起来,早已不存在的 kb 不再认", () => {
    for (const view of studioViews.views) expect(parseDeepLink(`mosael://open?view=${view}`)).toEqual({ view });
    expect(parseDeepLink("mosael://open?view=kb")).toBeNull();
  });
});

describe("mosael:// 深链解析", () => {
  it("接受白名单内的 view", () => {
    expect(parseDeepLink("mosael://open?view=statistics")).toEqual({ view: "statistics" });
    expect(parseDeepLink("mosael://open?view=workflows")).toEqual({ view: "workflows" });
    expect(parseDeepLink("mosael://open?view=publish&id=abc123")).toEqual({ view: "publish", id: "abc123" });
  });

  it("官网社区页的「在 Mosael 中打开」:没装的插件、没添加的模板,各自只在对应页面上认", () => {
    expect(parseDeepLink("mosael://open?view=plugins&market=dev.mosael.remotion")).toEqual({
      view: "plugins", market: "dev.mosael.remotion",
    });
    expect(parseDeepLink("mosael://open?view=workflows&template=product_pitch_short")).toEqual({
      view: "workflows", template: "product_pitch_short",
    });
    // 放错页面、字符集不对,整条不认 —— 不是"忽略那个参数照常跳",免得半截生效。
    expect(parseDeepLink("mosael://open?view=workflows&market=dev.mosael.remotion")).toBeNull();
    expect(parseDeepLink("mosael://open?view=plugins&template=x")).toBeNull();
    expect(parseDeepLink("mosael://open?view=plugins&market=../../x")).toBeNull();
    expect(parseDeepLink("mosael://open?view=workflows&template=Full-Video")).toBeNull();
  });

  it("邀请链接(ADR 0054):码交给界面,页面一律是首页;字符集不对整条不认", () => {
    expect(parseDeepLink("mosael://open?join=Ab_c-12345678")).toEqual({ view: "home", join: "Ab_c-12345678" });
    // 带了 join 就只认 join:别的参数不跟着生效,免得一条链接既加入工作区又跳到别处。
    expect(parseDeepLink("mosael://open?join=Ab_c-12345678&view=admin")).toEqual({ view: "home", join: "Ab_c-12345678" });
    expect(parseDeepLink("mosael://open?join=short")).toBeNull();
    expect(parseDeepLink("mosael://open?join=../../etc/passwd")).toBeNull();
    expect(parseDeepLink("mosael://open?join=")).toBeNull();
    expect(parseDeepLink("mosael://join?code=Ab_c-12345678")).toBeNull();
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
    expect(deepLinkFromArgv(["C:\\app.exe", "--flag", "mosael://open?view=notes"])).toEqual({ view: "notes" });
    expect(deepLinkFromArgv(["C:\\app.exe", "--flag"])).toBeNull();
    // 混着一个不合法的和一个合法的:取合法的那个,不因为前一个失败就放弃。
    expect(deepLinkFromArgv(["app", "mosael://run?x=1", "mosael://open?view=media"])).toEqual({
      view: "media",
    });
  });
});
