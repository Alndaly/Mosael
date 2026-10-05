/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 对话里读技能的那一步说人话:「用了技能:做带货短视频」,点开是它读到的做法(ADR 0040 §4)。
 * 一个 `use_skill` 加一串 JSON 对用户没意义;失败的照普通工具行画,原因看得见。
 */

vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return { useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key] ?? key };
});
vi.mock("@/features/agent/decisionsContext", () => ({ useToolCallConfirmation: () => null }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
vi.mock("@/api/client", () => ({
  assetFileUrl: () => "",
  assetPreviewUrl: () => "",
  assetThumbnailUrl: () => "",
  getAsset: vi.fn(),
}));

import { ToolCalls, type ToolCall } from "@/features/agent/ToolCalls";

afterEach(cleanup);

const DONE: ToolCall = {
  id: "t1",
  name: "use_skill",
  args: { name: "short-video-ads" },
  status: "done",
  result: {
    details: {
      data: {
        name: "short-video-ads",
        title: "做带货短视频",
        source: "工作区成员写的",
        instructions: "## 三段卖点\n先用 analyze_asset 看商品图",
        files: [{ path: "references/卖点模板.md", size: 10 }],
      },
    },
  },
};

describe("用了技能", () => {
  it("折叠时一句人话,点开是做法和带的文件", () => {
    const view = render(<ToolCalls tools={[DONE]} />);
    const row = screen.getByRole("button", { name: /用了技能:做带货短视频/ });
    expect(row.textContent).toContain("工作区成员写的");
    expect(view.container.textContent).not.toContain("先用 analyze_asset");
    fireEvent.click(row);
    const body = view.container.querySelector("[data-slot='skill-body']");
    expect(body?.textContent).toContain("三段卖点");
    expect(body?.textContent).toContain("先用 analyze_asset 看商品图");
    expect(body?.textContent).toContain("references/卖点模板.md");
    expect(view.container.textContent).not.toContain("\"instructions\"");
  });

  it("还在读的时候说「正在读技能」", () => {
    render(<ToolCalls tools={[{ ...DONE, status: "running", result: undefined }]} />);
    expect(screen.getByText("正在读技能:short-video-ads")).toBeInTheDocument();
  });

  it("失败的照普通工具行画,原因看得见", () => {
    const view = render(
      <ToolCalls tools={[{ id: "t2", name: "use_skill", args: { name: "nope" }, status: "error", result: "没有叫「nope」的技能" }]} />,
    );
    expect(view.container.textContent).toContain("use_skill");
    expect(view.container.textContent).toContain("没有叫「nope」的技能");
    expect(view.container.textContent).not.toContain("用了技能");
  });
});
