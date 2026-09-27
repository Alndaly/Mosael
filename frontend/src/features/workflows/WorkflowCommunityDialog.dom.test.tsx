/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 工作流社区:卡片网格 → 点开一页详情(和插件市场同一个目录弹窗)。
 *
 * 用户报过的几件事在这里各有一条:内容和 header 的外间距要一致;卡片上的「已添加」要写出字、
 * 不是一个没说明的绿勾;「运行前需要」每一条要说**这台机器上齐没齐**,而不是每条配同一个勾;
 * 主操作要贴着正在看的那个模板,不在底栏。
 */

//: 模板目录和前置条件的状态都由后端给(文案只有那一份)。
vi.mock("@/api/client", () => ({
  fetchWorkflowTemplates: async () => [
    {
      id: "translated_dub",
      name: "视频译配 · 字幕与配音",
      description: "逐句转写、逐句翻译、按原时间码铺字幕,再逐条配音。",
      stages: ["选择视频", "生成逐字稿"],
      requirements: [
        { text: "可用的转写引擎", check: "transcription_engine", optional: false },
        { text: "人声分离引擎", check: "separation_engine", optional: false },
        { text: "有人说话的视频素材", check: "", optional: false },
      ],
    },
    {
      id: "full_video_generation",
      name: "从主题到完整视频",
      description: "输入一个主题,生成脚本和视觉圣经。",
      stages: ["输入主题"],
      requirements: [
        { text: "AI 对话模型", check: "chat_model", optional: false },
        { text: "旁白可选:克隆音色", check: "cloned_voice", optional: true },
      ],
    },
  ],
  fetchWorkflowTemplateChecks: async () => [
    { check: "chat_model", status: "met" },
    { check: "cloned_voice", status: "missing" },
    { check: "transcription_engine", status: "met" },
    { check: "separation_engine", status: "missing" },
  ],
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { WorkflowCommunityDialog } from "@/features/workflows/WorkflowCommunityDialog";

const ADDED = {
  id: "w1", workspace_id: "ws", name: "译配", description: "", revision: 1, graph_hash: "", created_at: "", updated_at: "",
  graph: { nodes: [], edges: [], meta: { template_id: "translated_dub" } },
};

function renderDialog({ onInstall = vi.fn(), onOpenChange = vi.fn() } = {}) {
  //: 模板目录现在从接口来(文案只有后端一份),所以弹窗要在 QueryClientProvider 里。
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowCommunityDialog
        open
        workspaceId="ws"
        workflows={[ADDED]}
        installingId={null}
        onOpenChange={onOpenChange}
        onInstall={onInstall}
      />
    </QueryClientProvider>,
  );
  const dialog = screen.getByRole("dialog");
  const slot = (name: string) => dialog.querySelector<HTMLElement>(`[data-slot="${name}"]`);
  return { dialog, header: slot("modal-header")!, body: slot("modal-body")!, footer: slot("modal-footer"), onInstall, onOpenChange };
}

const paddingX = (element: HTMLElement) => element.className.split(/\s+/).filter((name) => /^(p|px|pl|pr)-/.test(name));
const card = (name: string) => screen.getAllByRole("article").find((one) => within(one).queryByRole("button", { name }))!;

describe("工作流社区弹窗的版式", () => {
  it("正文和头部的左右边距是同一个;不再有和选中项脱节的底栏", () => {
    const { header, body, footer } = renderDialog();
    expect(paddingX(header)).toContain("px-6");
    const bodyX = paddingX(body);
    expect(bodyX, `正文的左右边距:${bodyX.join(" ")}`).toContain("px-6");
    expect(bodyX).not.toContain("p-0");
    expect(footer).toBeNull();
  });

  it("每个模板一张卡;卡片里的说明截成三行 —— 不能被 block 覆盖掉", async () => {
    renderDialog();
    const list = await screen.findByRole("list", { name: "wfCommunityTitle" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    const description = card("视频译配 · 字幕与配音").querySelector<HTMLElement>(".line-clamp-3")!;
    expect(description.textContent).toContain("逐句转写");
    expect(description.className.split(/\s+/)).not.toContain("block");
  });

  it("加过的模板写出「已添加」,不是一个没说明的绿勾", async () => {
    renderDialog();
    await screen.findByRole("list", { name: "wfCommunityTitle" });
    expect(within(card("视频译配 · 字幕与配音")).getByText("wfCommunityInstalled")).toBeTruthy();
    expect(within(card("从主题到完整视频")).queryByText("wfCommunityInstalled")).toBeNull();
  });

  it("卡片上说缺几样:分离引擎没装 → 缺 1 项;可选的旁白缺了不算", async () => {
    renderDialog();
    await screen.findByRole("list", { name: "wfCommunityTitle" });
    expect(await within(card("视频译配 · 字幕与配音")).findByText("wfCommunityReqMissing")).toBeTruthy();
    expect(within(card("从主题到完整视频")).getByText("wfCommunityReqReady")).toBeTruthy();
  });

  it("「条件已齐」筛选只留能直接跑的", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByText("wfCommunityReqReady");
    await user.click(screen.getByRole("button", { name: "wfCommunityFilterReady 1" }));
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(card("从主题到完整视频")).toBeTruthy();
  });

  it("从卡片直接添加", async () => {
    const user = userEvent.setup();
    const { onInstall } = renderDialog();
    await screen.findByRole("list", { name: "wfCommunityTitle" });
    await user.click(within(card("从主题到完整视频")).getByRole("button", { name: "wfCommunityAddShort" }));
    expect(onInstall).toHaveBeenCalledWith("full_video_generation");
  });
});

describe("工作流详情", () => {
  it("每条前置条件带着它此刻的状态:齐了 / 缺 / 运行时选择", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByText("wfCommunityReqMissing");
    await user.click(within(card("视频译配 · 字幕与配音")).getByRole("button", { name: "视频译配 · 字幕与配音" }));

    const states = Object.fromEntries(
      Array.from(document.querySelectorAll<HTMLElement>("[data-requirement-state]")).map((row) => [
        row.textContent?.replace(/wfReqStatus\w+$/, ""),
        row.dataset.requirementState,
      ]),
    );
    expect(states).toEqual({ 可用的转写引擎: "met", 人声分离引擎: "missing", 有人说话的视频素材: "runtime" });
    expect(screen.getByText("wfReqStatusMissing")).toBeTruthy();
  });

  it("可选的缺了说「可选」,不报警", async () => {
    const user = userEvent.setup();
    renderDialog();
    await screen.findByText("wfCommunityReqReady");
    await user.click(within(card("从主题到完整视频")).getByRole("button", { name: "从主题到完整视频" }));
    expect(screen.getByText("wfReqStatusOptional")).toBeTruthy();
    expect(screen.queryByText("wfReqStatusMissing")).toBeNull();
  });

  it("主操作在详情头上;加过的写「再添加一个副本」", async () => {
    const user = userEvent.setup();
    const { onInstall } = renderDialog();
    await screen.findByRole("list", { name: "wfCommunityTitle" });
    await user.click(within(card("视频译配 · 字幕与配音")).getByRole("button", { name: "视频译配 · 字幕与配音" }));
    await user.click(screen.getByRole("button", { name: "wfCommunityAddAgain" }));
    expect(onInstall).toHaveBeenCalledWith("translated_dub");
  });

  it("键盘打开、Esc 退回网格(不关弹窗),焦点回到那张卡", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();
    await screen.findByRole("list", { name: "wfCommunityTitle" });
    within(card("从主题到完整视频")).getByRole("button", { name: "从主题到完整视频" }).focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { level: 3, name: "从主题到完整视频" })).toBeTruthy();

    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(await screen.findByRole("list", { name: "wfCommunityTitle" })).toBeTruthy();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(within(card("从主题到完整视频")).getByRole("button", { name: "从主题到完整视频" }));
  });
});
