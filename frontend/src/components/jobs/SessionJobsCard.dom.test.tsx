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
import { beforeEach, describe, expect, it, vi } from "vitest";

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
import { PlanCard } from "@/features/agent/PlanCard";
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

/** 「任务计划」和「后台任务」并排(面板里上下紧挨着),一行一行的语法要一样。 */
const PLAN = [
  { step: "已完成的一步", status: "done" },
  { step: "正在做的一步", status: "in_progress" },
  { step: "还没开始的一步", status: "pending" },
];

function mountBoth() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <PlanCard plan={PLAN} />
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

  //: 题目是一颗文字按钮:悬停才出现下划线,不是整行都能点。
  const title = screen.getByRole("button", { name: "山间的清晨" });
  expect(title.className).toContain("hover:underline");
  //: 还在跑的那一行给取消。
  const cancelButton = screen.getByRole("button", { name: "jobCancel" });
  expect(cancelButton.className).toContain("hover:underline");
  fireEvent.click(cancelButton);
  await waitFor(() => expect(h.cancelJob).toHaveBeenCalledWith("run-1"));

  //: 点整行 → 任务详情。
  fireEvent.click(screen.getByText("山间的清晨"));
  await waitFor(() => expect(screen.getByTestId("job-detail").textContent).toBe("fail-1"));

  //: 失败那一行的「前往」落在它的生成记录上,同样是悬停下划线的文字按钮。
  const goto = screen.getByRole("button", { name: "chatJobsGoto" });
  expect(goto.className).toContain("hover:underline");
  fireEvent.click(goto);
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
  const { container } = mount();
  await screen.findByText("慢活");
  expect(screen.getByText("chatJobsElapsed")).toBeTruthy();
  //: 用时是次要信息:在主行下方那一行,不挤在主行右侧(和「任务计划」同一个位置约定)。
  expect(container.querySelector("[data-session-job] [data-inspector-note]")?.textContent).toContain("chatJobsElapsed");
});

/**
 * 维护者截图:同一个「智能体环境」面板里,上面「任务计划」每行是 状态圈 + 文字(右侧什么都没有);
 * 下面「后台任务」却多一个类型图标、右侧再写一遍「成功」。两块每一行说的都是同一件事,
 * 语法必须一样 —— 这组测试并排渲染两块,逐条钉住。
 */
describe("和「任务计划」同一套行语法", () => {
  it("① 同一套状态圈:成功/进行中/未开始都用同一个组件、同一组 class", async () => {
    h.jobs = [
      job({ id: "ok", status: "succeeded", progress: 1, payload: { subject: "做完的", receipt: { session_id: "s1" } } }),
      job({ id: "run", status: "running", progress: 0.4, payload: { subject: "在跑的", receipt: { session_id: "s1" } } }),
      job({ id: "wait", status: "queued", progress: 0, payload: { subject: "排队的", receipt: { session_id: "s1" } } }),
    ];
    const { container } = mountBoth();
    await screen.findByText("做完的");

    const planIcon = (status: string) =>
      container.querySelector(`[data-plan-step] [data-agent-status="${status}"]`);
    const jobIcon = (status: string) =>
      container.querySelector(`[data-session-job] [data-agent-status="${status}"]`);
    for (const status of ["done", "running", "pending"]) {
      expect(jobIcon(status), `任务侧的 ${status}`).toBeTruthy();
      expect(jobIcon(status)!.className, `两块的 ${status} 圈`).toBe(planIcon(status)!.className);
    }
    //: 而且两边都是同一种"行"(同一个 InspectorStatusRow 画出来的)。
    expect(container.querySelectorAll("[data-session-job] [data-inspector-row]")).toHaveLength(3);
    expect(container.querySelectorAll("[data-plan-step] [data-inspector-row]")).toHaveLength(3);
  });

  it("② 右侧不再重复一遍状态词;失败原因走说明行", async () => {
    h.jobs = [
      job({ id: "ok", status: "succeeded", progress: 1, payload: { subject: "做完的", receipt: { session_id: "s1" } } }),
      job({
        id: "fail", status: "failed", progress: 1,
        error: "provider said no", error_summary: "连接超时",
        payload: { subject: "失败的", receipt: { session_id: "s1" } },
      }),
      job({ id: "stop", status: "cancelled", progress: 1, payload: { subject: "被停下的", receipt: { session_id: "s1" } } }),
    ];
    const { container } = mountBoth();
    await screen.findByText("做完的");

    const rows = [...container.querySelectorAll("[data-session-job]")];
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      //: 状态只由左边的圈表达:成功/失败/已取消都不再在行里写字。
      expect(row.textContent).not.toMatch(/runStatus_(succeeded|failed|cancelled)/);
      expect(row.textContent).not.toContain("成功");
    }
    //: 失败要文字时,那块字在两块共用的位置 —— 主行下方那一行,不是右侧。
    const failed = container.querySelector('[data-session-job="fail"]')!;
    expect(failed.querySelector("[data-inspector-row]")!.textContent).not.toContain("连接超时");
    expect(failed.querySelector("[data-inspector-note]")!.textContent).toContain("连接超时");
  });

  it("③ 类型图标要么两块都有、要么都没有 —— 现在是都没有,一行只剩一颗圈", async () => {
    h.jobs = [
      job({ id: "ok", status: "succeeded", progress: 1, payload: { subject: "做完的", receipt: { session_id: "s1" } } }),
    ];
    const { container } = mountBoth();
    await screen.findByText("做完的");

    //: 完工行没有取消钮,所以主行里唯一一个 svg 就是状态圈;计划那侧同样。
    expect(container.querySelector("[data-session-job] [data-inspector-row]")!.querySelectorAll("svg")).toHaveLength(1);
    expect(container.querySelector("[data-plan-step] [data-inspector-row]")!.querySelectorAll("svg")).toHaveLength(1);
  });

  it("⑤ 在跑的排在最前,不被上一条做完的任务顶下去", async () => {
    h.jobs = [
      job({ id: "done", status: "succeeded", progress: 1, created_at: stamp(1), payload: { subject: "刚做完的", receipt: { session_id: "s1" } } }),
      job({ id: "run", status: "running", progress: 0.4, created_at: stamp(30), payload: { subject: "在跑的", receipt: { session_id: "s1" } } }),
      job({ id: "wait", status: "queued", created_at: stamp(2), payload: { subject: "排队的", receipt: { session_id: "s1" } } }),
    ];
    const { container } = mount();
    await screen.findByText("在跑的");
    const order = [...container.querySelectorAll("[data-session-job]")].map((row) => row.getAttribute("data-session-job"));
    expect(order).toEqual(["run", "wait", "done"]);
  });

  it("④ 进度/用时在主行下方的说明行里,和文字同一左缘", async () => {
    h.jobs = [
      job({ id: "run", status: "running", progress: 0.4, payload: { subject: "在跑的", receipt: { session_id: "s1" } } }),
    ];
    const { container } = mountBoth();
    await screen.findByText("在跑的");

    const main = container.querySelector("[data-session-job] [data-inspector-row]")!;
    const note = container.querySelector("[data-session-job] [data-inspector-note]")!;
    expect(note.textContent).toContain("40%");
    expect(main.textContent).not.toContain("40%");
    //: 说明行在主行之后,不是主行里的第三格。
    expect(main.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
