/**
 * 服务端明确拒绝的查询不重试 —— 不然每一个 404 都要请求两次、晚一秒才告诉人「已删除或无法访问」
 * (实测:点开被删的笔记,同一个 404 在 0.33 s 和 1.34 s 各来一次)。
 */
import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/transport";
import { createAppQueryClient, shouldRetryQuery } from "@/app/queryClient";

const status = (code: number) => new ApiError(`HTTP ${code}`, code, "");

describe("查询失败要不要再试一次", () => {
  it.each([400, 401, 403, 404, 409, 422])("%i:答案不会变,不再试", (code) => {
    expect(shouldRetryQuery(0, status(code))).toBe(false);
  });

  it.each([408, 429, 500, 502, 503])("%i:可能是一时的,再试一次", (code) => {
    expect(shouldRetryQuery(0, status(code))).toBe(true);
    expect(shouldRetryQuery(1, status(code)), "只再试一次").toBe(false);
  });

  it("断网这类不是 HTTP 答复的错误,再试一次", () => {
    expect(shouldRetryQuery(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetryQuery(1, new TypeError("Failed to fetch"))).toBe(false);
  });

  it("应用的 QueryClient 用的就是这条规则", () => {
    const client = createAppQueryClient(() => undefined, (key) => key);
    expect(client.getDefaultOptions().queries?.retry).toBe(shouldRetryQuery);
    expect(client.getDefaultOptions().queries?.staleTime).toBe(60_000);
  });
});
