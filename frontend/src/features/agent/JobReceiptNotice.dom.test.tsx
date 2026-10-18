/** @vitest-environment jsdom */

/**
 * 后台任务的回执是**一张任务卡**,不是一行冻结了语言的通知。
 *
 * 真机上的毛病:回执只有 `job_id`/`asset_ids`,正文是后端拼好的一句中文(失败原因取 `job.error`),
 * 界面只能原样显示 —— 英文界面里原因永远是中文,也没有「查看任务 / 前往生成记录 / 重新取回」。
 * 成功的那一条还会常驻在对话里,和右侧「后台任务」列表说的是同一件事。
 *
 * 钉住:
 *   · 成功回执不常驻(它交给「后台任务」列表);
 *   · 失败回执是一张能点的卡,原因按当前语言(payload.error_summary,后端出口翻好);
 *   · 「查看任务」打开任务详情、「前往生成记录」跳到生成记录;
 *   · 后端说 `retrievable` 时摆「重新取回」,点它调的是不重新提交的那个接口。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  getJob: vi.fn(),
  fetchJobKinds: vi.fn(),
  listGenerationJobs: vi.fn(),
  retrieveGeneration: vi.fn(),
  gotoRecord: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

const CATALOG = {
  kinds: [
    { kind: "ai_generation", label: "生成", announce: "always", affects: ["assets"], view: "ai", record_field: "session_id" },
    { kind: "tts", label: "配音", announce: "always", affects: ["assets"], view: "ai", record_field: "session_id" },
  ],
  fallback: { kind: "", label: "任务", announce: "always", affects: [], view: null, record_field: null },
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: h.toast }));
vi.mock("@/api/client", () => ({
  api: vi.fn(),
  getJob: h.getJob,
  fetchJobKinds: h.fetchJobKinds,
  cancelJob: vi.fn(),
  listJobEvents: vi.fn(async () => []),
  listJobChildren: vi.fn(async () => []),
  regenerateAssetProxy: vi.fn(),
}));
vi.mock("@/api/domains/generation", () => ({
  listGenerationJobs: h.listGenerationJobs,
  retrieveGeneration: h.retrieveGeneration,
}));
vi.mock("@/lib/deepLink", () => ({
  gotoRecord: h.gotoRecord,
  VIEW_RECORD_EVENTS: { ai: "mosael:ai-record" },
}));
vi.mock("@/components/jobs/JobDetailDialog", () => ({
  JobDetailDialog: ({ job }: { job: { id: string } | null }) =>
    job ? <div data-testid="job-detail">{job.id}</div> : null,
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { JobReceiptNotice } from "./JobReceiptNotice";

const SUBJECT = "一只在雨里等车的柴犬,".repeat(12);

function mount(payload: Record<string, unknown>, content = "「配音 1」已完成。") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <JobReceiptNotice content={content} payload={payload} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  h.getJob.mockReset();
  h.fetchJobKinds.mockReset().mockResolvedValue(CATALOG);
  h.listGenerationJobs.mockReset().mockResolvedValue([]);
  h.retrieveGeneration.mockReset().mockResolvedValue({ generation: { id: "gen-1" }, job: { id: "job-2" } });
  h.gotoRecord.mockReset();
  h.toast.success.mockReset();
  h.toast.error.mockReset();
});

it("成功的回执不在对话里常驻 —— 它交给右侧「后台任务」列表", () => {
  const { container } = mount({ job_id: "job-1", status: "succeeded", kind: "tts", subject: "配音 1" });
  expect(container.querySelector("[data-job-receipt]")).toBeNull();
  expect(container.textContent).toBe("");
});

it("失败回执是一张任务卡:原因按当前语言,动作找得到那条任务和那条生成记录", async () => {
  h.getJob.mockResolvedValue({
    id: "job-1", workspace_id: "w1", kind: "ai_generation", status: "failed", progress: 1,
    message: "生成失败", payload: {}, error: "backend restarted", error_summary: "The backend restarted",
    created_at: "2026-10-18T08:00:00", updated_at: "2026-10-18T08:00:00",
  });
  mount({
    job_id: "job-1",
    status: "failed",
    kind: "ai_generation",
    subject: SUBJECT,
    generation_id: "gen-1",
    generation_session_id: "gen-session-1",
    error_key: "jobErr_backendRestart",
    error_params: {},
    error: "",
    error_summary: "The backend restarted and interrupted this task; please start it again",
    error_detail: null,
    error_hint: null,
  });

  //: 英文界面下原因来自出口翻好的那一句,不是正文里那句冻结的中文。
  expect(screen.getByText("The backend restarted and interrupted this task; please start it again")).toBeTruthy();
  //: 完整 subject 在 DOM 里(Truncate 只裁视觉,悬停看全文),没有被静默切掉。
  expect(screen.getByText(SUBJECT)).toBeTruthy();

  fireEvent.click(screen.getByText("chatJobsOpenTask"));
  await waitFor(() => expect(screen.getByTestId("job-detail").textContent).toBe("job-1"));

  fireEvent.click(screen.getByText("chatJobsGotoGeneration"));
  expect(h.gotoRecord).toHaveBeenCalledWith("/ai?tab=create", "mosael:ai-record", "gen-session-1");
});

it("非生成类失败:按种类说清是哪一类任务,「前往」是去它的结果页", async () => {
  const { container } = mount({
    job_id: "job-9", status: "failed", kind: "tts", subject: "配音 1",
    error_key: "", error_params: {}, error: "连接超时", error_summary: "连接超时",
  });
  //: 标题里用的是目录给的种类名(「配音失败」),不是笼统的「任务失败」。
  expect(container.querySelector("[data-job-receipt]")?.textContent).toContain("failureOfKind");
  //: 目录是异步取的:view 到了才知道这一行有没有「前往」。
  expect(await screen.findByText("chatJobsGoto")).toBeTruthy();
  expect(screen.queryByText("chatJobsGotoGeneration")).toBeNull();
});

it("后端说 retrievable 时才摆「重新取回」,点它走不重新提交的那个接口", async () => {
  h.listGenerationJobs.mockResolvedValue([{ id: "gen-1", retrievable: true }]);
  mount({
    job_id: "job-1", status: "failed", kind: "ai_generation", subject: "出图",
    generation_id: "gen-1", generation_session_id: "gen-session-1", workspace_id: "w1",
    error_key: "", error_params: {}, error: "下载成片时断了", error_summary: "下载成片时断了",
  });

  const retrieve = await screen.findByText("chatReceiptRetrieve");
  expect(h.listGenerationJobs).toHaveBeenCalledWith("w1", expect.objectContaining({ sessionId: "gen-session-1" }));
  fireEvent.click(retrieve);
  await waitFor(() => expect(h.retrieveGeneration).toHaveBeenCalledWith("gen-1"));
});

it("不可免费取回时不摆「重新取回」", async () => {
  h.listGenerationJobs.mockResolvedValue([{ id: "gen-1", retrievable: false }]);
  mount({
    job_id: "job-1", status: "failed", kind: "ai_generation", subject: "出图",
    generation_id: "gen-1", generation_session_id: "gen-session-1", workspace_id: "w1",
    error_key: "", error_params: {}, error: "ComfyUI 说这次不行", error_summary: "ComfyUI 说这次不行",
  });
  await waitFor(() => expect(h.listGenerationJobs).toHaveBeenCalled());
  expect(screen.queryByText("chatReceiptRetrieve")).toBeNull();
});

it("被停下的回执是灰的「已停止」,照样点得开任务详情", async () => {
  h.getJob.mockResolvedValue({
    id: "job-3", workspace_id: "w1", kind: "tts", status: "cancelled", progress: 0.4,
    message: "已取消", payload: {}, error: null, error_summary: null,
    created_at: "2026-10-18T08:00:00", updated_at: "2026-10-18T08:00:00",
  });
  const { container } = mount({ job_id: "job-3", status: "cancelled", kind: "tts", subject: "配音 2" });
  const card = container.querySelector<HTMLElement>("[data-job-receipt]");
  expect(card?.textContent).toContain("genStopped");
  fireEvent.click(screen.getByText("chatJobsOpenTask"));
  await waitFor(() => expect(screen.getByTestId("job-detail").textContent).toBe("job-3"));
});
