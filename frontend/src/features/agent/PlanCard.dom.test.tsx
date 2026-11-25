/** @vitest-environment jsdom */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

import { PlanCard } from "./PlanCard";

describe("任务计划卡片", () => {
  it("做完的计划进入历史后默认收成一行,点开才陈列", () => {
    const history = [
      [
        { step: "旧计划第一步", status: "done" as const },
        { step: "旧计划第二步", status: "done" as const },
      ],
    ];

    render(<PlanCard plan={null} history={history} />);

    expect(screen.getByText("agentPlanHistory")).toBeTruthy();
    expect(screen.queryByText("旧计划第一步")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "agentPlanHistory" }));

    expect(screen.getByText("旧计划第一步")).toBeTruthy();
    expect(screen.getByText("旧计划第二步")).toBeTruthy();
  });

  it("当前计划默认展开,点标题才收起", () => {
    render(<PlanCard plan={[{ step: "正在做", status: "in_progress" }]} />);

    expect(screen.getByText("agentPlan")).toBeTruthy();
    expect(screen.getByText("正在做")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "agentPlan" }));

    expect(screen.queryByText("正在做")).toBeNull();
  });

  it("历史里未完成的计划标出「未完成」和完成度", () => {
    render(<PlanCard plan={null} history={[[{ step: "确实没做完", status: "pending" }]]} />);

    fireEvent.click(screen.getByRole("button", { name: "agentPlanHistory" }));

    expect(screen.getByText("确实没做完")).toBeTruthy();
    expect(screen.getByText(/agentPlanUnfinished/).textContent).toContain("0/1");
  });
});
