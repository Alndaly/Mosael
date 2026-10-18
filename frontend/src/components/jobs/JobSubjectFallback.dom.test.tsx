/** @vitest-environment jsdom */

/**
 * 生成任务**没写提示词**时,三处任务展示(回执卡 / 「本对话的后台任务」 / 任务中心)要自己
 * 说清「这是哪来的」:按**当前语言** + **任务种类**(useJobKinds 的种类名)+ **素材份数**拼一句。
 *
 * 后端把 `payload.subject` 收窄成「只放用户自己写的那句」(没写就是空串)—— 于是展示层不能再拿
 * 空字符串当标题,也不能拿喂给模型的整段正文顶上去。这里钉住:
 *   · 只挂 2 个素材:三处都显示「从 2 个素材 AI 生成」,切英文是 "AI generation from 2 assets";
 *   · 有提示词:照旧显示完整提示词(不回归);
 *   · 没有素材数可用:只说种类(种类名本来就在行上),不重复、不空着。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  locale: "zh-CN" as "zh-CN" | "en-US",
  jobs: [] as any[],
  getJob: vi.fn(),
  gotoRecord: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  const table = (locale: string) => (messages as Record<string, Record<string, string>>)[locale];
  return {
    useI18n: () => (key: string) => table(h.locale)[key],
    usePreferences: () => ({ locale: h.locale }),
  };
});
vi.mock("sonner", () => ({ toast: h.toast }));
vi.mock("@/api/client", () => ({
  api: vi.fn(async () => ({})),
  cancelJob: vi.fn(async () => ({})),
  clearTaskCenter: vi.fn(async () => ({})),
  getJob: h.getJob,
  //: 种类名由后端目录按请求语言翻好 —— 这里按当前语言给一份最小的。
  fetchJobKinds: async () => ({
    kinds: [{
      kind: "ai_generation",
      label: h.locale === "zh-CN" ? "AI 生成" : "AI generation",
      announce: "always",
      affects: ["assets"],
      view: "ai",
      record_field: "session_id",
    }],
    fallback: {
      kind: "", label: h.locale === "zh-CN" ? "任务" : "Task",
      announce: "always", affects: [], view: null, record_field: null,
    },
  }),
  topLevelJobsQuery: (workspaceId: string) => ({
    queryKey: ["jobs", workspaceId, "top-level"],
    queryFn: async () => h.jobs,
  }),
  taskCenterQuery: (workspaceId: string) => ({
    queryKey: ["jobs", workspaceId, "task-center"],
    queryFn: async () => ({ jobs: h.jobs, cleared_at: null }),
  }),
  listJobEvents: vi.fn(async () => []),
  listJobChildren: vi.fn(async () => []),
  regenerateAssetProxy: vi.fn(),
}));
vi.mock("@/api/domains/generation", () => ({
  listGenerationJobs: vi.fn(async () => []),
  retrieveGeneration: vi.fn(async () => ({})),
}));
vi.mock("@/lib/deepLink", () => ({
  gotoRecord: h.gotoRecord,
  VIEW_RECORD_EVENTS: { ai: "mosael:ai-record" },
}));
vi.mock("@/components/jobs/JobDetailDialog", () => ({
  JobDetailDialog: () => null,
}));

import { messages } from "@/app/messages";
import { TooltipProvider } from "@/components/ui/tooltip";
import { JobReceiptNotice } from "@/features/agent/JobReceiptNotice";
import { SessionJobsCard } from "./SessionJobsCard";
import { TaskCenter } from "./TaskCenter";

const t = (key: string) => (messages as Record<string, Record<string, string>>)[h.locale][key];

const STAMP = "2026-10-18T08:00:00";

function job(extra: Record<string, unknown> = {}) {
  return {
    id: "job-1",
    workspace_id: "w1",
    kind: "ai_generation",
    status: "succeeded",
    progress: 1,
    message: null,
    error: null,
    error_summary: null,
    payload: {},
    created_at: STAMP,
    updated_at: STAMP,
    ...extra,
  };
}

/** 只挂 2 个素材、没写提示词的那条生成(后端现在把 subject 存成空串)。 */
const NO_PROMPT = {
  subject: "",
  request: {
    prompt: "",
    source_assets: [
      { asset_id: "a", role: "reference_image" },
      { asset_id: "b", role: "reference_image" },
    ],
  },
};

function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  h.locale = "zh-CN";
  h.jobs = [];
  h.getJob.mockReset();
  h.gotoRecord.mockReset();
  h.toast.success.mockReset();
  h.toast.error.mockReset();
  cleanup();
});

it("任务中心:只挂素材没写提示词 → 按当前语言说清从 2 个素材来的", async () => {
  h.jobs = [job({ payload: NO_PROMPT })];
  mount(<TaskCenter workspaceId="w1" />);

  fireEvent.click(screen.getByRole("button", { name: t("taskCenter") }));
  expect(await screen.findByText("从 2 个素材 AI 生成")).toBeTruthy();

  //: 切到英文界面:同一份数据,那句话跟着当前语言走。
  h.locale = "en-US";
  cleanup();
  h.jobs = [job({ payload: NO_PROMPT })];
  mount(<TaskCenter workspaceId="w1" />);
  fireEvent.click(screen.getByRole("button", { name: t("taskCenter") }));
  expect(await screen.findByText("AI generation from 2 assets")).toBeTruthy();
});

it("「本对话的后台任务」:同一份数据说同一句话", async () => {
  h.jobs = [job({ payload: { ...NO_PROMPT, receipt: { session_id: "s1" } } })];
  mount(<SessionJobsCard workspaceId="w1" sessionId="s1" />);

  expect(await screen.findByText("从 2 个素材 AI 生成")).toBeTruthy();

  h.locale = "en-US";
  cleanup();
  h.jobs = [job({ payload: { ...NO_PROMPT, receipt: { session_id: "s1" } } })];
  mount(<SessionJobsCard workspaceId="w1" sessionId="s1" />);
  expect(await screen.findByText("AI generation from 2 assets")).toBeTruthy();
});

it("回执卡:失败的回执也说清从 2 个素材来的(份数由后端结构化带出)", async () => {
  const payload = {
    job_id: "job-1",
    status: "failed",
    kind: "ai_generation",
    subject: "",
    source_asset_count: 2,
    error_key: "",
    error_params: {},
    error: "连接超时",
    error_summary: "连接超时",
  };
  mount(<JobReceiptNotice content="「刚才那个任务」失败了。" payload={payload} />);

  expect(await screen.findByText("从 2 个素材 AI 生成")).toBeTruthy();

  h.locale = "en-US";
  cleanup();
  mount(<JobReceiptNotice content="「刚才那个任务」失败了。" payload={payload} />);
  expect(await screen.findByText("AI generation from 2 assets")).toBeTruthy();
});

it("有提示词:照旧显示完整提示词,不被那句话顶掉", async () => {
  const prompt = "一只在雨里等车的柴犬,".repeat(30);
  h.jobs = [job({ payload: { ...NO_PROMPT, subject: prompt, request: { prompt, source_assets: [] } } })];
  mount(<TaskCenter workspaceId="w1" />);

  fireEvent.click(screen.getByRole("button", { name: t("taskCenter") }));
  expect(await screen.findByText(prompt)).toBeTruthy();
});

it("没有素材数可用:只说种类(行上本来就有种类名),不重复、不空着", async () => {
  h.jobs = [job({ payload: { subject: "", request: { prompt: "", source_assets: [] } } })];
  mount(<TaskCenter workspaceId="w1" />);

  fireEvent.click(screen.getByRole("button", { name: t("taskCenter") }));
  //: 种类名照旧在行上;subject 为空时不另起一句 —— 「只说种类」,不说成「AI 生成 AI 生成」。
  expect(await screen.findAllByText("AI 生成")).toHaveLength(1);
});
