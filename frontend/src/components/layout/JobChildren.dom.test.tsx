/** @vitest-environment jsdom */

/**
 * 子任务清单有**两个消费方**:任务中心的任务详情,和工作流的运行历史。
 *
 * 它对工作流那边尤其要紧:循环体里的节点**不发事件**(子图不带 job),所以按节点画的那份
 * 清单在一次跑六镜的运行里只有一个条目在转圈,十几分钟不动 —— 看起来像卡死了。而那六次
 * 出片各自都建了任务,数据一直在,只是工作流这一侧从没去取。
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({ listJobChildren: vi.fn() }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({ runStatus_running: "进行中", runStatus_succeeded: "已完成", runStatus_failed: "失败" })[key] ?? key,
}));
// 名字来自后端的任务目录(ADR-0018),这里不经网络。
vi.mock("@/components/layout/jobKinds", () => ({
  useJobKinds: () => ({ kindOf: (kind: string) => ({ label: kind === "ai_generation" ? "AI 生成" : "任务" }) }),
}));

import { JobChildrenList } from "@/components/layout/JobChildren";

const job = (id: string, kind: string, status: string, message = "") =>
  ({ id, kind, status, message }) as never;

describe("子任务清单", () => {
  it("把每一条的种类和状态都摆出来", () => {
    render(
      <JobChildrenList>
        {[job("1", "ai_generation", "succeeded"), job("2", "ai_generation", "running", "第 2 镜")]}
      </JobChildrenList>,
    );
    expect(screen.getAllByText("AI 生成")).toHaveLength(2);
    expect(screen.getByText("已完成")).toBeTruthy();
    expect(screen.getByText("进行中")).toBeTruthy();
    expect(screen.getByText("第 2 镜")).toBeTruthy();
  });

  it("排队中也算在跑", () => {
    // queued 和 pending 都还没结束 —— 显示成"失败"色会吓人一跳。
    render(<JobChildrenList>{[job("1", "ai_generation", "queued"), job("2", "ai_generation", "pending")]}</JobChildrenList>);
    expect(screen.getAllByText("进行中")).toHaveLength(2);
  });

  it("一条都没有时不占位置", () => {
    const { container } = render(<JobChildrenList>{[]}</JobChildrenList>);
    expect(container.firstChild).toBeNull();
  });
});
