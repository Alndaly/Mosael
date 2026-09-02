/** @vitest-environment jsdom */
/**
 * 任务做完了,它改动的东西就得跟着刷新。
 *
 * 真机反馈:从链接下完的视频不出现在素材库,要刷新页面才看得见 —— 而"下载完成"的提示
 * 就弹在眼前。任务中心是唯一知道"哪个任务刚变成完成态"的地方,所以刷新放在这里一处;
 * 让每个页面各自轮询是同一件事写十遍,而漏掉一个页面就是一个"要刷新才看得见"的 bug。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// vi.mock 的工厂会被提升到文件顶部,所以共享状态要走 vi.hoisted,否则工厂执行时它还不存在。
const h = vi.hoisted(() => ({ apiMock: vi.fn(), state: { jobs: [] as any[] } }));
vi.mock("@/api/client", () => ({ api: h.apiMock }));

import { TooltipProvider } from "@/components/ui/tooltip";
import { TaskCenter } from "./TaskCenter";

function mount(initial: any[]) {
  // **一开始就得有活跃任务**:任务列表的轮询间隔是"有在跑的 1.5 秒、没有的 8 秒",
  // 先渲染空列表再塞任务的话,要等 8 秒才拉第二次 —— 那是测试自己的坑,不是被测代码的。
  h.state.jobs = initial;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidated: unknown[][] = [];
  const original = client.invalidateQueries.bind(client);
  client.invalidateQueries = ((filters: any) => {
    if (filters?.queryKey) invalidated.push(filters.queryKey);
    return original(filters);
  }) as typeof client.invalidateQueries;
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TaskCenter workspaceId="w1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return invalidated;
}

beforeEach(() => {
  h.state.jobs = [];
  h.apiMock.mockReset();
  h.apiMock.mockImplementation(async () => h.state.jobs);
});

/** 先让任务**确实被看到过**处于运行中,再翻成完成 —— 这正是真实的那一幕。
 *
 * 不能只 sleep 一下就翻:第一次拉取要是直接拿到 succeeded,组件只会把它记进基线而不认为
 * 「刚刚完成」,于是什么都不刷新 —— 那是测试自己的竞态,不是被测代码的毛病。
 * 判据用运行中图标(active 非空时任务中心按钮转圈),它就是"running 已经进到组件里了"。 */
const running = (kind: string) =>
  [{ id: "j1", kind, status: "running", progress: 0.5, message: null, error: null, payload: {} }];

/** 等组件**确实看到过**运行中,再把它翻成完成 —— 这正是真实的那一幕。
 *
 * 不能只 sleep 一下就翻:第一次拉取要是直接拿到终态,组件只会把它记进基线而不认为
 * 「刚刚完成」,于是什么都不刷新 —— 那是测试自己的竞态。判据用任务中心按钮上的转圈图标,
 * 它就是"running 已经进到组件里了"。 */
async function finish(kind: string, status: "succeeded" | "failed", error: string | null = null) {
  await waitFor(() => expect(document.querySelector(".animate-mosael-spin")).not.toBeNull(), {
    timeout: 4000,
  });
  h.state.jobs = [{ id: "j1", kind, status, progress: 1, message: null, error, payload: {} }];
}

describe("任务完成后刷新它改动过的数据", () => {
  it("从链接导入下完,素材库自己就刷新了(不用刷页面)", async () => {
    const invalidated = mount(running("url_import"));
    await finish("url_import", "succeeded");
    await waitFor(
      () => expect(invalidated.some((key) => key[0] === "assets")).toBe(true),
      { timeout: 4000 },
    );
  });

  it("配音做完,序列也一起刷新 —— 它往时间线上放了片段", async () => {
    const invalidated = mount(running("subtitle_dub"));
    await finish("subtitle_dub", "succeeded");
    await waitFor(
      () => {
        expect(invalidated.some((key) => key[0] === "assets")).toBe(true);
        expect(invalidated.some((key) => key[0] === "sequences")).toBe(true);
      },
      { timeout: 4000 },
    );
  });

  it("失败的任务不刷新 —— 没有产物可看,白跑一趟请求", async () => {
    const invalidated = mount(running("url_import"));
    await finish("url_import", "failed", "boom");
    await new Promise((r) => setTimeout(r, 3000));
    expect(invalidated.some((key) => key[0] === "assets")).toBe(false);
  });
});
