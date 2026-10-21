/**
 * jsdom:令牌读写走 `window.localStorage`,这条用例要断言"令牌还在"。
 * @vitest-environment jsdom
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiAllowingUnauthorized, setAuthToken, setUnauthorizedHandler } from "@/api/transport";

/**
 * `apiAllowingUnauthorized` 的 401 **不能**把人从本机账号踢出去。
 *
 * 踩到的现象:一打开账号/设置页就回到登录页 —— 那一页问 MosaelCloud `/me`,而云端 401 说的是
 * 「云那边没登录」。以前 `failure()` 顺手在 401 上清令牌,`localSession: false` 的守卫被绕过,
 * 于是云端的 401 把本机会话也一起清了。
 */
describe("云端 401 不等于本机退出", () => {
  const onUnauthorized = vi.fn();

  beforeEach(() => {
    setAuthToken("local-token");
    setUnauthorizedHandler(onUnauthorized);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "需要先登录 MosaelCloud" }), { status: 401 })),
    );
  });

  afterEach(() => {
    setUnauthorizedHandler(null);
    vi.unstubAllGlobals();
    onUnauthorized.mockClear();
  });

  it("apiAllowingUnauthorized 的 401:抛给调用方,不触发登出", async () => {
    await expect(apiAllowingUnauthorized("/api/cloud/v1/me")).rejects.toBeTruthy();
    expect(onUnauthorized).not.toHaveBeenCalled();
    //: 令牌还在 —— 回来之后还是同一个本机账号。
    expect(window.localStorage.getItem("mosael.auth.token")).toBe("local-token");
  });
});
