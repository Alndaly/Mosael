/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useUnusableNodeReasons } from "@/features/workflows/useUnusableNodeReasons";

/**
 * 缺的那几个类型攒成**一个**请求问(接口收多个 types),结果仍按类型各自缓存 —— 检查器只问选中的那一个时,
 * 不再发请求。此前一个类型一个请求:一张挂着二十个缺插件节点的图打开就并发二十个。
 */

const asked: string[][] = [];

beforeEach(() => {
  asked.length = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    const types = url.searchParams.getAll("types");
    asked.push(types);
    const body = types.filter((type) => type !== "plugin.ok.fine").map((type) => ({ type, reason: `${type} 没接` }));
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
});
afterEach(() => vi.unstubAllGlobals());

function wrapper(client: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

it("缺的几个类型一个请求问完,按类型分给各自的缓存", async () => {
  const client = new QueryClient();
  const types = ["plugin.a.x", "llm", "plugin.b.y", "plugin.ok.fine", "plugin.a.x"];
  const { result } = renderHook(() => useUnusableNodeReasons(types), { wrapper: wrapper(client) });
  await waitFor(() => expect(result.current.size).toBe(2));
  expect(asked).toEqual([["plugin.a.x", "plugin.b.y", "plugin.ok.fine"]]);
  expect(result.current.get("plugin.b.y")).toBe("plugin.b.y 没接");
  expect(result.current.has("plugin.ok.fine")).toBe(false);

  // 检查器只问选中的那一个:缓存里有,不再发请求
  const inspector = renderHook(() => useUnusableNodeReasons(["plugin.a.x"]), { wrapper: wrapper(client) });
  expect(inspector.result.current.get("plugin.a.x")).toBe("plugin.a.x 没接");
  expect(asked).toHaveLength(1);
});
