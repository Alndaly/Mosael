/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return { useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] ?? key };
});

import { ToolResultCard } from "./toolResultShapes";

describe("通用列表工具结果", () => {
  it("摘要只摊标量，嵌套字段统一留在原始输出", () => {
    render(<ToolResultCard value={{ status: "running", payload: { a: 1 }, nested: [1, 2] }} />);
    expect(screen.getByText("running")).not.toBeNull();
    expect(screen.queryByText("payload")).toBeNull();
    expect(screen.queryByText("nested")).toBeNull();
  });

  it("说明超长时单行省略，不折成两行", () => {
    const description = "输入一个主题，生成创意主旨、脚本和视觉圣经；角色和场景先到资产库里认，已有的直接用它的参考图，新出现的才画三视图 / 设定图并存入资产。";
    render(
      <ToolResultCard
        value={[{ id: "wf-1", name: "长明灯 · 第一集 · 第 1 场", description }]}
      />,
    );

    const node = screen.getByText(description);
    expect(node.className).toContain("truncate");
    expect(node.className).not.toContain("line-clamp-2");
  });
});
