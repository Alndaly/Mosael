/** @vitest-environment jsdom */

/**
 * 任务绑的工作流**已经被删了**的时候,那一格不该是个能点的按钮。
 *
 * 此前它照样能点、照样跳去工作流页 —— 而那一页当然找不到它。界面上写着「绑定的工作流已删除」,
 * 却又请你去那儿看一眼,等于在说"它可能还在";用户点过去、翻一遍、什么都没有,只会更糊涂。
 *
 * 「还没读到」和「读过了,不在」也必须分开:列表还在路上时把每个任务都诬告一遍「工作流已删除」,
 * 比不显示更糟。
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      taskWorkflowGone: "绑定的工作流已删除",
      taskWorkflowLoading: "正在读取…",
      taskNoWorkflow: "未绑定工作流",
      taskOpenWorkflow: "打开工作流",
      wfBoundWorkflow: "绑定工作流",
      taskWorkflowGoneDesc: "这个任务触发时会失败",
      taskWorkflowDesc: "任务要跑的那张图",
    })[key] ?? key,
  usePreferences: () => ({ locale: "zh" }),
}));

import { BoundWorkflowRow } from "./boundWorkflowRow";

const WORKFLOW = { id: "wf-1", name: "每日剪辑", description: "" } as never;

function mount(workflowId: string, workflows: unknown[], isPending = false) {
  return render(
    <BoundWorkflowRow
      workflowId={workflowId}
      workflows={workflows as never}
      isPending={isPending}
    />,
  );
}

describe("任务绑定的工作流", () => {
  it("工作流还在:可以点开去看", () => {
    mount("wf-1", [WORKFLOW]);
    const button = screen.getByRole("button");
    expect(button.textContent).toContain("每日剪辑");
  });

  it("已经被删了:不是按钮,没有可去的地方", () => {
    mount("wf-1", []);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("绑定的工作流已删除");
  });

  it("列表还在路上时不许先诬告一遍", () => {
    // 读完之前谁都说不准。这时候说"已删除"是把"还不知道"当成了结论。
    mount("wf-1", [], true);
    expect(screen.queryByText("绑定的工作流已删除")).toBeNull();
    expect(screen.getByRole("button").textContent).toContain("正在读取…");
  });

  it("压根没绑过:仍然可以点去挑一个", () => {
    mount("", []);
    expect(screen.getByRole("button").textContent).toContain("未绑定工作流");
  });
});
