/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 时间线里的思考块。
 *
 * 三条判据各自对应一个具体的坏结果:
 * 思考混进正文 → 会被落库成回答、被复制按钮一起复制走;
 * 结束后仍展开 → 把答案挤到屏幕外(Claude/Codex 都是结束即收);
 * 重开会话时顶着"思考中" → 一个永远转不完的圈。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("streamdown", () => ({
  Streamdown: ({ children }: { children: string }) => <div>{children}</div>,
  CodeBlockCopyButton: () => <button type="button" />,
}));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: () => {} }) }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: undefined }) }));

import { AgentTurnContent } from "@/components/agent/ToolCalls";

describe("思考块", () => {
  it("进行中展开并转圈", () => {
    const { container } = render(
      <AgentTurnContent timeline={[{ type: "thinking", text: "先看看素材库", done: false }]} />,
    );
    expect(screen.getByText("agentThinking")).toBeTruthy();
    expect(screen.getByText("先看看素材库")).toBeTruthy();
    // 转圈用 animate-openstudio-spin —— 全仓库都是它,思考块此前是唯一用 animate-spin 的
    // 特例(那两个动画曲线不一样,并排时看得出快慢不同)。
    expect(container.querySelector(".animate-openstudio-spin")).toBeTruthy();
  });

  it("结束后默认收起,标题仍在", () => {
    render(<AgentTurnContent timeline={[{ type: "thinking", text: "推理过程", done: true }]} />);
    expect(screen.getByText("agentThought")).toBeTruthy();
    // "它想过"本身是信息,标题保留;正文收起,免得把答案挤到屏幕外。
    expect(screen.queryByText("推理过程")).toBeNull();
  });

  it("思考不混进正文", () => {
    render(
      <AgentTurnContent
        timeline={[
          { type: "thinking", text: "内心独白", done: true },
          { type: "text", text: "这是回答" },
        ]}
      />,
    );
    expect(screen.getByText("这是回答")).toBeTruthy();
    expect(screen.queryByText("内心独白")).toBeNull();
  });

  it("保序:思考 → 工具 → 思考,顺序本身是信息", () => {
    const { container } = render(
      <AgentTurnContent
        timeline={[
          { type: "thinking", text: "a", done: true },
          { type: "text", text: "中间" },
          { type: "thinking", text: "b", done: true },
        ]}
      />,
    );
    const labels = [...container.querySelectorAll("button, div")]
      .map((el) => el.textContent ?? "")
      .filter((text) => text === "agentThought" || text === "中间");
    expect(labels.length).toBeGreaterThanOrEqual(3);
  });
});
