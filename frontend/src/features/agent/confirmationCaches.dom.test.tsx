/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, expect, it, vi } from "vitest";

let executed: { id: string }[] = [];
const api = vi.fn(async (_path: string) => executed);

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: (path: string) => api(path),
}));

import { useRefreshWhenCardsLand } from "@/features/agent/confirmationCaches";

function Watcher({ workspaceId }: { workspaceId: string }) {
  useRefreshWhenCardsLand(workspaceId);
  return null;
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <Watcher workspaceId="w1" />
    </QueryClientProvider>,
  );
  const key = ["confirmations", "w1", "executed"];
  // 等首次取数落进缓存再轮询:在飞的那次会被重取掐掉,那样「首次」就成了轮询取回的那一批。
  const loaded = () => waitFor(() => expect(client.getQueryData(key)).toBeDefined());
  const poll = () => act(() => client.refetchQueries({ queryKey: key }));
  const invalidatedAssets = () =>
    invalidate.mock.calls.some(([filters]) => JSON.stringify(filters?.queryKey) === JSON.stringify(["assets"]));
  return { loaded, poll, invalidatedAssets };
}

afterEach(() => {
  executed = [];
  api.mockClear();
});

/**
 * 用户反馈:智能体删了两个素材,工具结果写着「已删除」,素材库里两个都还在。那张卡是自动放行批的 ——
 * 界面上没有人点「批准」,于是批准按钮上挂的那次缓存失效从没发生,开着的素材库一直是旧的。
 */
it("不是这个界面批的卡执行完了,素材缓存也要失效", async () => {
  const { loaded, poll, invalidatedAssets } = mount();
  await loaded();
  const query = new URL(api.mock.calls[0][0], "http://x").searchParams;
  expect(query.get("workspace_id")).toBe("w1");
  expect(query.get("status")).toBe("executed");

  executed = [{ id: "auto-approved-delete" }];
  await poll();

  await waitFor(() => expect(invalidatedAssets()).toBe(true));
});

it("打开时已经执行完的那批不算新落地", async () => {
  executed = [{ id: "long-ago" }];
  const { loaded, poll, invalidatedAssets } = mount();
  await loaded();
  await poll();

  expect(invalidatedAssets()).toBe(false);
});

it("窗口藏起来时不轮询,回到前台当场查一次", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const { loaded } = mount();
    await loaded();
    const before = api.mock.calls.length;

    act(() => focusManager.setFocused(false));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(api.mock.calls.length).toBe(before);

    act(() => focusManager.setFocused(true));
    await waitFor(() => expect(api.mock.calls.length).toBeGreaterThan(before));
  } finally {
    focusManager.setFocused(undefined);
    vi.useRealTimers();
  }
});
