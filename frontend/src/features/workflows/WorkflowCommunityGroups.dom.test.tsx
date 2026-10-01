/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 「几选一」的前置条件:分析类模板的数据来源,TikHub 和内嵌浏览器满足一条就能跑。
 *
 * 没接 TikHub 的人照样能用浏览器那一路 —— 卡片上不该说「缺 1 项」把他劝退;但 TikHub 那一条也不能假装齐了,
 * 详情里如实说它没配,只是「另一种方式可用」。组里两条都查得了、又都没齐时,才算缺。
 */

vi.mock("@/api/client", () => ({
  fetchWorkflowTemplates: async () => [
    {
      id: "account_analysis",
      name: "自媒体账号运营诊断",
      description: "取账号资料和最近作品,写运营诊断。",
      stages: ["填主页链接"],
      requirements: [
        { text: "AI 对话模型", check: "chat_model", optional: false, group: "" },
        { text: "TikHub 取数", check: "tikhub_account", optional: false, group: "data_source" },
        { text: "或者用内嵌浏览器取数", check: "", optional: false, group: "data_source" },
      ],
    },
    {
      id: "comment_insights",
      name: "两条路都查得了",
      description: "组里两条都是能查的,都没齐。",
      stages: ["填作品链接"],
      requirements: [
        { text: "AI 对话模型", check: "chat_model", optional: false, group: "" },
        { text: "TikHub 取评论", check: "tikhub_comments", optional: false, group: "data_source" },
        { text: "转写引擎", check: "transcription_engine", optional: false, group: "data_source" },
      ],
    },
  ],
  fetchWorkflowTemplateChecks: async () => [
    { check: "chat_model", status: "met" },
    { check: "tikhub_account", status: "missing" },
    { check: "tikhub_comments", status: "missing" },
    { check: "transcription_engine", status: "missing" },
  ],
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { WorkflowCommunityDialog } from "@/features/workflows/WorkflowCommunityDialog";

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowCommunityDialog
        open
        workspaceId="ws"
        workflows={[]}
        installingId={null}
        onOpenChange={vi.fn()}
        onInstall={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

const card = (name: string) => screen.getAllByRole("article").find((one) => within(one).queryByRole("button", { name }))!;

describe("几选一的前置条件", () => {
  it("TikHub 没接、浏览器那条可用:卡片说条件已齐", async () => {
    renderDialog();
    await screen.findByRole("list", { name: "wfCommunityTitle" });
    expect(await within(card("自媒体账号运营诊断")).findByText("wfCommunityReqReady")).toBeTruthy();
  });

  it("详情里 TikHub 那条如实说没配,只是另一种方式可用", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByText("wfCommunityReqReady");
    await user.click(within(card("自媒体账号运营诊断")).getByRole("button", { name: "自媒体账号运营诊断" }));
    const states = Object.fromEntries(
      Array.from(document.querySelectorAll<HTMLElement>("[data-requirement-state]")).map((row) => [
        row.textContent?.replace(/wfReqStatus\w+$/, ""),
        row.dataset.requirementState,
      ]),
    );
    expect(states).toEqual({ "AI 对话模型": "met", "TikHub 取数": "alternative", 或者用内嵌浏览器取数: "runtime" });
    expect(screen.getByText("wfReqStatusAlternative")).toBeTruthy();
    expect(screen.queryByText("wfReqStatusMissing")).toBeNull();
  });

  it("组里两条都没齐:算缺", async () => {
    renderDialog();
    await screen.findByRole("list", { name: "wfCommunityTitle" });
    expect(await within(card("两条路都查得了")).findByText("wfCommunityReqMissing")).toBeTruthy();
  });
});
