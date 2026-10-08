/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, expect, it, vi } from "vitest";

let executed: { id: string; status: string; writes: string[] }[] = [];
const api = vi.fn(async (_path: string) => executed);

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: (path: string) => api(path),
}));

import { assetKeys, confirmationKeys, projectKeys, skillKeys } from "@/api/queryKeys";
import { invalidateAfterDecision, useRefreshWhenCardsLand } from "@/features/agent/confirmationCaches";

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

  executed = [{ id: "auto-approved-delete", status: "executed", writes: ["assets", "sequences"] }];
  await poll();

  await waitFor(() => expect(invalidatedAssets()).toBe(true));
});

it("打开时已经执行完的那批不算新落地", async () => {
  executed = [{ id: "long-ago", status: "executed", writes: ["assets"] }];
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

/**
 * 智能体改笔记(edit_note)批准之后:打开着的那篇重取,编辑器里实时看到改动 —— 不等用户切走再回来。
 * 刷什么由卡自己说(`writes`,ADR 0053);自动放行批的卡同样走这里(见上面那条)。
 */
it("批完一张改笔记的卡,笔记详情和列表都要失效", () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");

  invalidateAfterDecision(client, "w1", { status: "executed", writes: ["notes"] });

  const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  expect(keys).toContain(JSON.stringify(["note"]));
  expect(keys).toContain(JSON.stringify(["notes"]));
});

/**
 * 卡声明改了什么,对应的缓存就过期 —— 用页面里真实的键形状放进缓存再看,而不是比对清单字面量(前缀对不上时字面量
 * 照样「包含」,缓存却不失效)。项目、发布任务是手写清单那会儿实测漏过的:在剪辑页里批掉「删除项目 X」,切换器还列着 X。
 */
it("卡声明了改项目、发布任务、工作流、技能、素材,那几份缓存都过期;没声明的不动", () => {
  const client = new QueryClient();
  const seeded = {
    projects: projectKeys.list("w1"),
    publishTasks: ["publish-tasks", "w1"],
    workflowRuns: ["workflow-runs", "wf1"],
    skills: skillKeys.detail("w1", "my-skill"),
    assets: assetKeys.pages({ workspace_id: "w1" }),
  };
  const untouched = ["boards", "w1"];
  for (const key of [...Object.values(seeded), untouched]) client.setQueryData(key, []);

  invalidateAfterDecision(client, "w1", [
    { status: "executed", writes: ["projects", "assets", "sequences"] },
    { status: "executed", writes: ["publish_tasks"] },
    { status: "failed", writes: ["workflows"] },
    { status: "executed", writes: ["skills"] },
  ]);

  const stale = Object.entries(seeded)
    .filter(([, key]) => !client.getQueryState(key)?.isInvalidated)
    .map(([name]) => name);
  expect(stale, "这些缓存批完卡之后还是旧的").toEqual([]);
  expect(client.getQueryState(untouched)?.isInvalidated, "没有哪张卡说改了画板").toBe(false);
});

it("拒掉的卡什么都没做:只刷卡本身", () => {
  const client = new QueryClient();
  client.setQueryData(projectKeys.list("w1"), []);
  client.setQueryData(confirmationKeys.toDecide("w1"), []);

  invalidateAfterDecision(client, "w1", { status: "rejected", writes: ["projects"] });

  expect(client.getQueryState(projectKeys.list("w1"))?.isInvalidated).toBe(false);
  expect(client.getQueryState(confirmationKeys.toDecide("w1"))?.isInvalidated).toBe(true);
});
