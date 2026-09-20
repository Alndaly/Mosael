/** @vitest-environment jsdom */

/**
 * 子任务清单有**两个消费方**:任务中心的任务详情,和工作流的运行历史。
 *
 * 它对工作流那边尤其要紧:循环体里的节点**不发事件**(子图不带 job),所以按节点画的那份
 * 清单在一次跑六镜的运行里只有一个条目在转圈,十几分钟不动 —— 看起来像卡死了。而那六次
 * 出片各自都建了任务,数据一直在,只是工作流这一侧从没去取。
 *
 * **每一行还要能就地展开看过程**:此前一行只有「AI 生成 / 成功 / 生成完成」三个词,那一步做了
 * 什么、失败时模型原样返回了什么都看不到。展开是**懒加载**的 —— 一次运行能派生几十条子任务,
 * 进详情就全拉一遍,代价落在"我只想看一眼状态"的那种用法上。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const listJobEvents = vi.fn(async () => [
  { id: "e1", type: "job.succeeded", payload: { message: "出片完成" }, created_at: "2026-09-20T10:00:00Z" },
]);
const listJobChildren = vi.fn(async () => []);
vi.mock("@/api/client", () => ({
  listJobChildren: (...args: unknown[]) => listJobChildren(...(args as [])),
  listJobEvents: (...args: unknown[]) => listJobEvents(...(args as [])),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({ runStatus_running: "进行中", runStatus_succeeded: "已完成", runStatus_failed: "失败" })[key] ?? key,
  usePreferences: () => ({ locale: "zh" }),
}));
// 名字来自后端的任务目录(ADR-0018),这里不经网络。
vi.mock("@/components/layout/jobKinds", () => ({
  useJobKinds: () => ({ kindOf: (kind: string) => ({ label: kind === "ai_generation" ? "AI 生成" : "任务" }) }),
}));

import { JobChildrenList } from "@/components/layout/JobChildren";

const job = (id: string, kind: string, status: string, message = "", error = "") =>
  ({ id, kind, status, message, error }) as never;

function mount(rows: unknown[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobChildrenList>{rows as never}</JobChildrenList>
    </QueryClientProvider>,
  );
}

describe("子任务清单", () => {
  it("把每一条的种类和状态都摆出来", () => {
    mount([job("1", "ai_generation", "succeeded"), job("2", "ai_generation", "running", "第 2 镜")]);
    expect(screen.getAllByText("AI 生成")).toHaveLength(2);
    expect(screen.getByText("已完成")).toBeTruthy();
    expect(screen.getByText("进行中")).toBeTruthy();
    expect(screen.getByText("第 2 镜")).toBeTruthy();
  });

  it("排队中也算在跑", () => {
    // queued 和 pending 都还没结束 —— 显示成"失败"色会吓人一跳。
    mount([job("1", "ai_generation", "queued"), job("2", "ai_generation", "pending")]);
    expect(screen.getAllByText("进行中")).toHaveLength(2);
  });

  it("一条都没有时不占位置", () => {
    const { container } = mount([]);
    expect(container.firstChild).toBeNull();
  });

  it("没展开就不去拉执行记录", () => {
    listJobEvents.mockClear();
    mount([job("1", "ai_generation", "succeeded"), job("2", "ai_generation", "succeeded")]);
    // 懒加载是这条行为的全部意义:几十条子任务的详情不该在打开弹窗时一次性打出去。
    expect(listJobEvents).not.toHaveBeenCalled();
  });

  it("点开那一行才去拉,并把这一条自己的执行记录摆出来", async () => {
    listJobEvents.mockClear();
    mount([job("1", "ai_generation", "succeeded")]);
    fireEvent.click(screen.getByRole("button"));
    expect(listJobEvents).toHaveBeenCalledWith("1");
    expect(await screen.findByText("job.succeeded")).toBeTruthy();
    expect(screen.getByText("出片完成")).toBeTruthy();
  });

  it("失败原因就在展开的那一层里", async () => {
    // 此前行上只有一个红色的「失败」,原因整条藏在钻不进去的地方。
    mount([job("9", "ai_generation", "failed", "生成失败", "模型返回的 JSON 不符合 Schema")]);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByText("模型返回的 JSON 不符合 Schema")).toBeTruthy();
  });
});
