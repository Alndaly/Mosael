/** @vitest-environment jsdom */
/**
 * 官网工作流详情页「在 Mosael 中打开」:打开工作流社区,**选中那个模板**。
 *
 * 此前深链只带 view,应用切到工作流页就停了 —— 用户在官网看中的那个模板,到了应用里得自己再找一遍,
 * 看起来就是"点了没反应"。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  fetchWorkflowTemplates: async () => [
    { id: "full_video_generation", name: "从主题到完整视频", description: "a", stages: ["输入主题"], requirements: [] },
    { id: "product_pitch_short", name: "商品 → 带货口播短视频", description: "b", stages: ["填商品与卖点"], requirements: [] },
  ],
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { WorkflowCommunityDialog } from "@/features/workflows/WorkflowCommunityDialog";

it("打开时选中官网指定的那个模板,而不是列表第一个", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowCommunityDialog
        open
        workflows={[]}
        installingId={null}
        focusTemplate="product_pitch_short"
        onOpenChange={vi.fn()}
        onInstall={vi.fn()}
      />
    </QueryClientProvider>,
  );
  const dialog = await screen.findByRole("dialog");
  // 右侧详情的标题就是选中的那一条。
  expect(await within(dialog).findByRole("heading", { level: 3, name: "商品 → 带货口播短视频" })).toBeTruthy();
});
