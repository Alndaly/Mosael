/**
 * 登录排障用的请求追踪:只认白名单站点,只记 origin+path(查询串里有 code / ticket,一律不记)。
 */
import { describe, expect, it } from "vitest";

// CommonJS is intentional: accountViews 加载的是同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { makeFilter, watchSession } = require("./netTrace.cjs") as {
  makeFilter: (hosts?: string[]) => (url: string) => { pathname: string } | null;
  watchSession: (
    session: unknown,
    onEvent: (event: Record<string, unknown>) => void,
    options?: { hosts?: string[]; seen?: WeakSet<object> },
  ) => void;
};

function fakeSession() {
  const handlers: Record<string, (details: Record<string, unknown>) => void> = {};
  const session = {
    webRequest: {
      onCompleted: (_filter: unknown, cb: (d: Record<string, unknown>) => void) => { handlers.done = cb; },
      onErrorOccurred: (_filter: unknown, cb: (d: Record<string, unknown>) => void) => { handlers.error = cb; },
      onBeforeRedirect: (_filter: unknown, cb: (d: Record<string, unknown>) => void) => { handlers.redirect = cb; },
    },
  };
  return { session, handlers };
}

describe("登录排障的请求追踪", () => {
  it("只认白名单站点,别的站点一个都不记", () => {
    const filter = makeFilter();
    expect(filter("https://channels.weixin.qq.com/platform/home?x=1")?.pathname).toBe("/platform/home");
    expect(filter("https://open.weixin.qq.com/connect/qrconnect?appid=1")).toBeTruthy();
    expect(filter("https://example.com/")).toBeNull();
    expect(filter("not a url")).toBeNull();
  });

  it("完成 / 出错 / 重定向各记一条,只带 path 与状态,不带查询串", () => {
    const { session, handlers } = fakeSession();
    const events: Array<Record<string, unknown>> = [];
    watchSession(session, (e) => events.push(e));

    handlers.done({ url: "https://channels.weixin.qq.com/platform/home?sessionid=SECRET", method: "GET", statusCode: 200, resourceType: "xhr" });
    handlers.redirect({ url: "https://channels.weixin.qq.com/login.html?from=platform", method: "GET", statusCode: 302 });
    handlers.error({ url: "https://channels.weixin.qq.com/cgi-bin/x?code=SECRET", method: "POST", error: "net::ERR_ABORTED" });

    expect(events).toEqual([
      { kind: "done", method: "GET", path: "/platform/home", status: 200, resource: "xhr" },
      { kind: "redirect", method: "GET", path: "/login.html", status: 302, resource: "" },
      { kind: "error", method: "POST", path: "/cgi-bin/x", status: "net::ERR_ABORTED", resource: "" },
    ]);
    expect(JSON.stringify(events)).not.toContain("SECRET");
  });

  it("同一个 session 只挂一次(每建一个 tab 都会走到这里)", () => {
    const { session, handlers } = fakeSession();
    const seen = new WeakSet<object>();
    let calls = 0;
    watchSession(session, () => { calls += 1; }, { seen });
    watchSession(session, () => { calls += 1; }, { seen });
    handlers.done({ url: "https://channels.weixin.qq.com/a", method: "GET", statusCode: 200 });
    expect(calls).toBe(1);
  });
});
