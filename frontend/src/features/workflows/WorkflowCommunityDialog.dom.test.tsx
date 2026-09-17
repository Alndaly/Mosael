/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 工作流社区弹窗的间距。
 *
 * 用户报的是「内容的外间距和 header 的外间距不一致」:正文区是 p-0,左侧列表只靠自己 12px 的
 * 内边距,于是列表比标题、搜索框往外凸出一截。jsdom 量不了像素,钉住的是**决定间距的那几个类**。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { WorkflowCommunityDialog } from "@/features/workflows/WorkflowCommunityDialog";

function renderDialog() {
  render(<WorkflowCommunityDialog open workflows={[]} installingId={null} onOpenChange={vi.fn()} onInstall={vi.fn()} />);
  const dialog = screen.getByRole("dialog");
  const slot = (name: string) => dialog.querySelector<HTMLElement>(`[data-slot="${name}"]`)!;
  return { dialog, header: slot("modal-header"), body: slot("modal-body"), footer: slot("modal-footer") };
}

const paddingX = (element: HTMLElement) => element.className.split(/\s+/).filter((name) => /^(p|px|pl|pr)-/.test(name));

describe("工作流社区弹窗的间距", () => {
  it("正文和头部、底部的左右边距是同一个", () => {
    const { header, body, footer } = renderDialog();
    expect(paddingX(header)).toContain("px-6");
    expect(paddingX(footer)).toContain("px-6");
    const bodyX = paddingX(body);
    expect(bodyX, `正文的左右边距:${bodyX.join(" ")}`).toContain("px-6");
    expect(bodyX).not.toContain("p-0");
  });

  it("两列内侧留白对称,外侧不再各自加一层", () => {
    renderDialog();
    const list = screen.getByRole("listbox");
    const detail = list.nextElementSibling as HTMLElement;
    expect(list.className).toMatch(/\bmd:pr-5\b/);
    expect(detail.className).toMatch(/\bmd:pl-5\b/);
    for (const column of [list, detail]) {
      expect(column.className, column.className).not.toMatch(/(^|\s)(p|px|pl)-\d/);
    }
  });

  it("卡片里的说明截成两行 —— 不能被 block 覆盖掉", () => {
    renderDialog();
    const option = screen.getAllByRole("option")[0];
    const description = option.querySelector<HTMLElement>(".line-clamp-2")!;
    expect(description).not.toBeNull();
    expect(description.className.split(/\s+/)).not.toContain("block");
  });
});
