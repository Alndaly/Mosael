import { describe, expect, it } from "vitest";

import { planHistory } from "./PlanCard";

function updatePlan(steps: { step: string; status: string }[]) {
  return [
    {
      type: "tool" as const,
      tool: { id: "p", name: "update_plan", args: { steps }, status: "done" as const },
    },
  ];
}

describe("计划历史", () => {
  it("被新计划取代的 0/N 也保留在历史里", () => {
    const abandoned = [
      { step: "确定方向", status: "pending" },
      { step: "写脚本", status: "pending" },
    ];
    const finished = [
      { step: "确定方向:潮流运动鞋", status: "done" },
      { step: "写脚本:12 个镜头", status: "done" },
    ];

    expect(planHistory([updatePlan(abandoned), updatePlan(finished)])).toEqual([abandoned, finished]);
  });

  it("两份都做完时都留着", () => {
    const first = [{ step: "旧活", status: "done" }];
    const second = [{ step: "新活", status: "done" }];

    expect(planHistory([updatePlan(first), updatePlan(second)])).toEqual([first, second]);
  });

  it("只有未完成计划时也留着 —— 有些计划确实没做完", () => {
    const unfinished = [{ step: "还没做", status: "pending" }];
    expect(planHistory([updatePlan(unfinished)])).toEqual([unfinished]);
  });
});
