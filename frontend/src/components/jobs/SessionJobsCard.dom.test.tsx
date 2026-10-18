/** @vitest-environment jsdom */

/**
 * 右侧「本对话的后台任务」:只列**这次对话发起的**任务(按任务载荷里的回执会话过滤),
 * 进度、取消、结果各归各位;空的时候整块不渲染(和计划/子代理同一条规矩)。
 *
 * 它和「最近工具」是两件事:那边是每一次工具调用(读也出现、只留 6 条),这边是任务行
 * (跨轮次、跨重启、有进度、能取消)。卡片里用一句话把这条区别写给用户。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  jobs: [] as any[],
  cancelJob: vi.fn(async () => ({})),
  getJob: vi.fn(),
  fetchJobKinds: vi.fn(),
  gotoRecord: vi.fn(),
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
vi.mock("@/api/client", () => ({
  api: vi.fn(),
  topLevelJobsQuery: (workspaceId: string) => ({
    queryKey: ["jobs", workspaceId, "top-level"],
    queryFn: async () => h.jobs,
  }),
  cancelJob: h.cancelJob,
  getJob: h.getJob,
  fetchJobKinds: h.fetchJobKinds,
  listJobEvents: vi.fn(async () => []),
  listJobChildren: vi.fn(async () => []),
  regenerateAssetProxy: vi.fn(),
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
import { SessionJobsCard } from "./SessionJobsCard";

const stamp = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();

const job = (extra: Record<string, any>) => ({
  id: "job-1",
  workspace_id: "w1",
  kind: "ai_generation",
  status: "running",
  progress: 0,
  message: null,
  error: null,
  error_summary: null,
  payload: {},
  created_at: stamp(5),
  updated_at: stamp(0),
  ...extra,
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <SessionJobsCard workspaceId="w1" sessionId="s1" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  h.jobs = [];
  h.cancelJob.mockClear();
  h.getJob.mockReset();
  h.fetchJobKinds.mockReset().mockResolvedValue(CATALOG);
  h.gotoRecord.mockReset();
});

it("只列本对话发起的任务:状态、进度、失败原因各说各的", async () => {
  h.jobs = [
    job({
      id: "run-1", kind: "ai_generation", status: "running", progress: 0.4,
      //: 旧任务的 subject 只有前 80 字;完整提示词一直在 request.prompt 里 —— 行上要看全的那一份。
      payload: { subject: "雨里的柴犬".repeat(30).slice(0, 80), request: { prompt: "雨里的柴犬".repeat(30) }, receipt: { session_id: "s1" } },
    }),
    job({
      id: "fail-1", kind: "ai_generation", status: "failed", progress: 1,
      error: "provider said no", error_summary: "连接超时",
      payload: { subject: "山间的清晨", session_id: "gen-session-2", receipt: { session_id: "s1" } },
    }),
    job({
      id: "other", kind: "tts", status: "running", progress: 0,
      payload: { subject: "别的对话的配音", receipt: { session_id: "s2" } },
    }),
  ];
  const { container } = mount();

  await screen.findByText("雨里的柴犬".repeat(30));
  expect(screen.getByText("山间的清晨")).toBeTruthy();
  expect(screen.queryByText("别的对话的配音")).toBeNull();
  expect(screen.getByText("40%")).toBeTruthy();
  expect(screen.getByText("连接超时")).toBeTruthy();
  expect(container.querySelector("[data-session-jobs]")?.textContent).toContain("chatJobsScope");
  expect(container.querySelectorAll("[data-session-job]")).toHaveLength(2);

  //: 还在跑的那一行给取消。
  fireEvent.click(screen.getByLabelText("jobCancel"));
  await waitFor(() => expect(h.cancelJob).toHaveBeenCalledWith("run-1"));

  //: 点整行 → 任务详情。
  fireEvent.click(screen.getByText("山间的清晨"));
  await waitFor(() => expect(screen.getByTestId("job-detail").textContent).toBe("fail-1"));

  //: 失败那一行的「前往」落在它的生成记录上。
  fireEvent.click(screen.getByText("chatJobsGoto"));
  expect(h.gotoRecord).toHaveBeenCalledWith("/ai?tab=create", "mosael:ai-record", "gen-session-2");
});

it("没有本对话的任务时整块不渲染", async () => {
  h.jobs = [job({ id: "other", payload: { subject: "别的", receipt: { session_id: "s2" } } })];
  const { container } = mount();
  await waitFor(() => expect(h.fetchJobKinds).toHaveBeenCalled());
  expect(container.querySelector("[data-session-jobs]")).toBeNull();
  expect(container.textContent).toBe("");
});

it("还没报进度的在跑任务说「已跑 N 秒」,不是停在 0%", async () => {
  h.jobs = [
    job({ id: "run-2", status: "running", progress: 0, created_at: stamp(7), payload: { subject: "慢活", receipt: { session_id: "s1" } } }),
  ];
  mount();
  await screen.findByText("慢活");
  expect(screen.getByText("chatJobsElapsed")).toBeTruthy();
});
