/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  listWorkflowRuns: vi.fn(),
  listJobEvents: vi.fn(),
  listJobChildren: vi.fn(),
  listRunApprovals: vi.fn(),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  ...apiMocks,
}));
vi.mock("@/app/preferences", () => ({
  //: 花费那一句是个模板(「花费 {cost} · …」):留着 {cost} 才看得出填进去的是哪一句
  useI18n: () => (key: string) => (key === "wfHistoryCost" ? "wfHistoryCost[{cost}]" : key),
  usePreferences: () => ({ locale: "zh-CN", t: (key: string) => key }),
}));

import { WorkflowRunHistory } from "@/features/workflows/WorkflowRunHistory";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});
beforeEach(() => {
  //: 没有待批单是默认情形;要它的用例自己覆盖。返回 `undefined` 会让 react-query 每次报警。
  apiMocks.listRunApprovals.mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderHistory(viewedRunId: string | null = "j1", onViewRun = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowRunHistory
        workflowId="wf1"
        registry={{ get: () => undefined }}
        viewedRunId={viewedRunId}
        onViewRun={onViewRun}
        mode="docked"
        onModeChange={vi.fn()}
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

//: 用户点了停止的那一次:列表行说「已取消」(走 i18n,不是英文原文 cancelled),
//: 停下时在跑的那一步也说已取消,而不是一个红叉「失败」。
it("被停下的运行:这一页按的是「停止运行」,写已停止(ADR 0049);在跑的那一步显示已取消", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    { id: "j1", kind: "workflow", status: "cancelled", message: "", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {} },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([
    { id: "e1", job_id: "j1", type: "workflow.node.started", created_at: "2026-09-19T04:00:01Z", payload: { node_id: "gen", name: "生成" } },
    { id: "e2", job_id: "j1", type: "job.cancelled", created_at: "2026-09-19T04:00:10Z", payload: {} },
  ]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  renderHistory();

  expect(await screen.findByText("wfHistoryStopped")).toBeInTheDocument();
  expect(screen.queryByText("cancelled")).toBeNull();
  expect(await screen.findByText("wfStepCancelled")).toBeInTheDocument();
});

//: 「正在看哪一次」归编辑器:这里只显示它指的那一次,点别的一行是把选择交上去,自己不另记一份 ——
//: 此前面板自己记,于是在历史里点开旧的一次,画布和检查器还停在最近那次。
it("选中项由编辑器给;点另一行交给编辑器,面板自己不换", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    { id: "new", kind: "workflow", status: "succeeded", message: "最新一次", created_at: "2026-09-19T05:00:00", updated_at: "2026-09-19T05:00:10", payload: {} },
    { id: "old", kind: "workflow", status: "failed", message: "较早一次", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {} },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  const onViewRun = vi.fn();
  renderHistory("old", onViewRun);

  const older = (await screen.findByText("较早一次")).closest("button")!;
  const newer = screen.getByText("最新一次").closest("button")!;
  expect(older.getAttribute("aria-current")).toBe("true");
  expect(newer.getAttribute("aria-current")).toBeNull();
  expect(apiMocks.listJobEvents).toHaveBeenCalledWith("old");

  fireEvent.click(newer);
  expect(onViewRun).toHaveBeenCalledWith("new");
  expect(older.getAttribute("aria-current"), "面板不自己换,等编辑器给").toBe("true");
});

//: 一次运行花了多少钱(后端 run_costs 记在 result.costs):大模型的调用挂在运行上、生成挂在子任务上,一起算。
it("选中的那一次说清楚花了多少钱、几次计费调用、几次没能定价", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    {
      id: "j1", kind: "workflow", status: "succeeded", message: "完成", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {},
      result: { costs: { amounts: [{ currency: "CNY", micros: 1_300_000 }], calls: 3, unpriced: 1 } },
    },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  renderHistory();

  const line = await screen.findByTestId("run-costs");
  expect(line.textContent).toContain("wfHistoryCost");
  expect(line.textContent).toContain("wfHistoryCostUnpriced");
});

it("调用都没扣钱(失败了服务商什么都没回、免费的):说「未扣费」,不是「未定价」", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    {
      id: "j1", kind: "workflow", status: "failed", message: "失败", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {},
      result: { costs: { amounts: [], calls: 2, unpriced: 0 } },
    },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  renderHistory();

  const line = await screen.findByTestId("run-costs");
  expect(line.textContent).toContain("wfHistoryCostNotCharged");
  expect(line.textContent).not.toContain("wfHistoryCostNone");
});

it("一次计费调用都没有的运行不显示花费那一行", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    {
      id: "j1", kind: "workflow", status: "succeeded", message: "完成", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {},
      result: { costs: { amounts: [], calls: 0, unpriced: 0 } },
    },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  renderHistory();

  await screen.findByText("完成");
  expect(screen.queryByTestId("run-costs")).toBeNull();
});

//: 维护者:「工作流等存在类似情况的失败的那个卡片 UI 也进行彻底的重构排版」—— 整轮失败是全应用那一份失败展示,那一句照跑挂的子任务说
it("这一轮跑挂了:一张失败展示,写后端摘好的那一句、认得出时的原因和怎么修,原文在「详情」里", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    {
      id: "j1", kind: "workflow", status: "failed", message: "工作流失败", created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10",
      payload: {}, result: {}, error: "子任务失败:「ComfyUI · http://x」生成失败:ComfyUI 执行失败:KSampler: boom",
      error_summary: "ComfyUI 执行到「KSampler」这一步出错", error_detail: "KSampler: boom",
      error_hint: { cause: "那台 ComfyUI 太旧", steps: [{ text: "升级", command: "pip install -U x" }] },
    },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  renderHistory();

  fireEvent.click(await screen.findByText("工作流失败"));
  const card = (await screen.findByText("ComfyUI 执行到「KSampler」这一步出错")).closest<HTMLElement>("[data-run-failed]")!;
  expect(card.getAttribute("role")).toBe("group");
  expect(card.querySelector("[data-failure-cause]")?.textContent).toBe("那台 ComfyUI 太旧");
  expect(card.querySelector("[data-failure-command] code")?.textContent).toBe("pip install -U x");
  expect(card.querySelector("[data-failure-detail]")?.textContent).toBe("KSampler: boom");
  expect(card.textContent, "原文那一整句不贴在卡上").not.toContain("http://x");
});

//: 单跑一个节点的那次运行:列表行标出「部分运行(目标:节点名)」—— 它和整跑长在同一张列表里,
//: 不标的话看不出这次为什么只有几步;载荷里没有 target_node_name 的整跑不标。
it("单跑一个节点的运行标注「部分运行(目标:节点名)」,整跑不标", async () => {
  apiMocks.listWorkflowRuns.mockResolvedValue([
    {
      id: "j1", kind: "workflow", status: "succeeded", message: "工作流完成:测试",
      created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10",
      payload: { target_node_id: "template-1", target_node_name: "润色文案" },
    },
    {
      id: "j2", kind: "workflow", status: "succeeded", message: "工作流完成:测试",
      created_at: "2026-09-19T03:00:00", updated_at: "2026-09-19T03:00:40",
      payload: {},
    },
  ]);
  apiMocks.listJobEvents.mockResolvedValue([]);
  apiMocks.listJobChildren.mockResolvedValue([]);
  renderHistory();

  const badge = await screen.findByText("wfHistoryPartialRun");
  expect(badge.getAttribute("data-run-partial")).not.toBeNull();
  expect(document.querySelectorAll("[data-run-partial]")).toHaveLength(1);
});

//: ADR 0074:一个面板,三段落,一条分隔线。下面这一组把六条硬规矩钉在 DOM 上 ——
//: 高度链、滚动责任、框的层数、段间分隔线、44px 行、详情默认展开。

const SUCCESS_RUN = {
  id: "j1", kind: "workflow", status: "succeeded", message: "完成",
  created_at: "2026-09-19T04:00:00", updated_at: "2026-09-19T04:00:10", payload: {},
};

const STEP_EVENTS = [
  { id: "e1", job_id: "j1", type: "workflow.node.started", created_at: "2026-09-19T04:00:01Z", payload: { node_id: "gen", name: "生成" } },
  { id: "e2", job_id: "j1", type: "workflow.node.finished", created_at: "2026-09-19T04:00:04Z", payload: { node_id: "gen", name: "生成", outputs: {} } },
  { id: "e3", job_id: "j1", type: "workflow.node.started", created_at: "2026-09-19T04:00:05Z", payload: { node_id: "post", name: "润色" } },
];

function approval(overrides: Record<string, unknown> = {}) {
  return {
    id: "ap-1", job_id: "j1", workflow_id: "wf1", node_id: "gate", node_name: "上线前确认",
    title: "要按这一版发布吗？", body: Array.from({ length: 10 }, (_, index) => `第 ${index + 1} 行稿子`).join("\n"),
    approve_label: "确认发布", reject_label: "先别发", allow_note: true,
    status: "pending", decision: "", feishu_delivery: "sent", feishu_delivery_reason: "",
    expires_at: null, created_at: "2026-09-19T04:00:00",
    ...overrides,
  };
}

function seed(runs: unknown[], opts: { approvals?: unknown[]; events?: unknown[] } = {}) {
  apiMocks.listWorkflowRuns.mockResolvedValue(runs);
  apiMocks.listJobEvents.mockResolvedValue(opts.events ?? []);
  apiMocks.listJobChildren.mockResolvedValue([]);
  apiMocks.listRunApprovals.mockResolvedValue(opts.approvals ?? []);
}

/** 一个元素自己是不是纵向滚动容器。 */
function scrollsY(el: HTMLElement): boolean {
  return /(?:^|\s)overflow-(?:y-)?(?:auto|scroll)(?:\s|$)/.test(el.className);
}

/** 整圈边:宽度类(不是 border-t / border-l 这类单边,也不是 border-border 这种颜色)。 */
function fullBorder(el: HTMLElement): boolean {
  return el.className.split(/\s+/).some((token) => /^border(?:-[1-8]|\[[^\]]+\])?$/.test(token));
}

/** 面板里**第二圈框**:圆角 + 整圈边,而且不是控件(按钮/输入框本来就带轮廓)。 */
function roundedBorderCards(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>('[class*="border"]')].filter((el) => {
    const control = el.closest("button, input, textarea, select, a, [role='button'], [role='combobox']") !== null;
    return !control && /(?:^|\s)rounded(?:-|$)/.test(el.className) && fullBorder(el);
  });
}

it("ADP 0074 决定 5:面板根是唯一滚动容器,头部吸顶;待批正文是唯一刻意的例外", async () => {
  seed([SUCCESS_RUN], { approvals: [approval()], events: STEP_EVENTS });
  renderHistory();

  const aside = (await screen.findByText("要按这一版发布吗？")).closest("aside") as HTMLElement;
  //: 面板根负责滚:高度由父级给(`h-full`),`min-h-0` 让它不按内容撑。
  expect(aside.className).toContain("overflow-y-auto");
  expect(aside.className).toContain("h-full");
  expect(aside.className).toContain("min-h-0");
  expect(aside.className).toContain("flex-col");
  //: 段间 12px 只有一种刻度。
  expect(aside.className).toContain("gap-3");

  //: 外面那层框(`DOCKABLE_PANEL_FRAME_CLASS`)一条 overflow 都不许写 —— 否则和根抢同一条属性。
  expect(aside.className.includes("overflow-x"), "外框不能再有一层 overflow-x").toBe(false);

  const scrollers = [aside, ...aside.querySelectorAll<HTMLElement>("*")].filter(scrollsY);
  const allowed = scrollers.filter((el) => el.hasAttribute("data-wf-run-approval-body"));
  expect(scrollers.length - allowed.length, "除面板根和待批正文,不该还有第三层滚动").toBe(1);
  expect(scrollers[0]).toBe(aside);
  expect(allowed.length, "待批正文是那一个刻意的例外").toBe(1);
  expect(allowed[0]?.getAttribute("data-wf-run-approval-body")).not.toBeNull();
  //: 旧的中间滚动层已经删掉 —— 高度链不再依赖任何 `flex-1`。
  expect(aside.querySelector("[data-wf-run-history-scroll]")).toBeNull();

  //: 头部在滚动区**里面**、吸顶;它不是在标题栏和滚动区之间的另一段。
  const header = aside.querySelector("[data-wf-run-history-header]") as HTMLElement;
  expect(header).toBeTruthy();
  for (const token of ["sticky", "top-0", "z-10"]) expect(header.className).toContain(token);
  expect(aside.contains(header)).toBe(true);
  expect(aside.children[0]).toBe(header);
});

it("ADP 0074 决定 1:里面没有第二圈框 —— 全是单边 border-t / border-l", async () => {
  seed([SUCCESS_RUN], { approvals: [approval()], events: STEP_EVENTS });
  renderHistory();

  const aside = (await screen.findByText("要按这一版发布吗？")).closest("aside") as HTMLElement;
  //: 唯一的一圈整框是面板自己:rounded-xl + border。
  expect(aside.className).toContain("rounded-xl");
  expect(fullBorder(aside)).toBe(true);
  //: 里面一块都没有。
  expect(roundedBorderCards(aside), "面板里出现了第二圈 rounded + border 的块").toEqual([]);

  const list = aside.querySelector("[data-wf-run-history-list]") as HTMLElement;
  const detail = aside.querySelector("[data-wf-run-history-detail]") as HTMLElement;
  //: 段与段之间**各一条** `border-t`,没有整圈边。
  for (const section of [list, detail]) {
    expect(section.className).toContain("border-t");
    expect(fullBorder(section)).toBe(false);
  }
  const notice = aside.querySelector("[data-wf-run-approval]") as HTMLElement;
  expect(fullBorder(notice)).toBe(false);
  expect(notice.className).toContain("border-l-2");
  expect(notice.className).toContain("border-primary");
  //: 三块底之一:待批段的浅强调底;它不再是一张自画底色的卡片。
  expect(notice.className).toContain("bg-accent/40");
  expect(notice.className).not.toContain("bg-card");
});

it("ADP 0074 决定 2:三块底 —— 面板、待批段的浅强调底、选中行的强调底;其余透明", async () => {
  seed([SUCCESS_RUN], { approvals: [approval()], events: STEP_EVENTS });
  renderHistory();

  const aside = (await screen.findByText("要按这一版发布吗？")).closest("aside") as HTMLElement;
  const selected = aside.querySelector('button[aria-current="true"]') as HTMLElement;
  expect(selected.className).toContain("bg-accent");
  //: 列表行自己不带底(只有悬停才用同一个强调色的浅一档)。
  for (const row of [...aside.querySelectorAll('[data-wf-run-history-list] > button')] as HTMLElement[]) {
    if (row === selected) continue;
    expect(/(?:^|\s)bg-(?!accent)/.test(row.className), `多出一块底:${row.className}`).toBe(false);
  }
  //: 步骤行平时透明,正在跑的那一步用强调底。
  const steps = [...aside.querySelectorAll("[data-wf-run-history-detail] li > button")] as HTMLElement[];
  const current = steps.find((el) => el.getAttribute("aria-current") === "step");
  expect(current, "当前步骤要能认出来").toBeTruthy();
  expect(current!.className).toContain("bg-accent");
  for (const step of steps) {
    if (step === current) continue;
    expect(step.className).not.toContain("bg-");
  }
});

it("ADP 0074 决定 4:列表行和步骤行都是 44px(min-h-11),耗时右对齐", async () => {
  seed([SUCCESS_RUN], { events: STEP_EVENTS });
  renderHistory();

  const aside = (await screen.findByText("完成")).closest("aside") as HTMLElement;
  await screen.findByText("润色");
  const listRows = [...aside.querySelectorAll("[data-wf-run-history-list] > button")] as HTMLElement[];
  const stepRows = [...aside.querySelectorAll("[data-wf-run-history-detail] li > button")] as HTMLElement[];
  expect(listRows.length).toBeGreaterThan(0);
  expect(stepRows.length).toBeGreaterThan(0);
  for (const row of [...listRows, ...stepRows]) {
    expect(row.className, "行高统一 44px").toContain("min-h-11");
  }
  //: 耗时 / 状态贴在行尾(右对齐)。
  const durations = [...aside.querySelectorAll("[data-wf-run-history-detail] .timecode")] as HTMLElement[];
  expect(durations.length).toBeGreaterThan(0);
  for (const duration of durations) expect(duration.className).toContain("ml-auto");
});

it("ADP 0074:详情默认展开最后选中的那次运行 —— 不用先点一下", async () => {
  seed([SUCCESS_RUN], { events: STEP_EVENTS });
  renderHistory();

  await screen.findByText("完成");
  //: 编辑器给的 `viewedRunId` 就是「最后选中的那次」:它的步骤直接在页面上。
  const detail = document.querySelector("[data-wf-run-history-detail]") as HTMLElement;
  expect(detail).toBeTruthy();
  expect(await screen.findByText("润色")).toBeInTheDocument();
  expect(detail.contains(screen.getByText("润色"))).toBe(true);
  //: 详情段里没有任何「展开这次运行」的开关 —— 它本来就是展开的。
  expect(screen.queryByRole("button", { name: /展开|expand/i })).toBeNull();
});

it("ADP 0074 决定 6:没有待批时待批段整块不渲染(不占位、不留线)", async () => {
  seed([SUCCESS_RUN], { events: STEP_EVENTS });
  renderHistory();

  const aside = (await screen.findByText("完成")).closest("aside") as HTMLElement;
  expect(aside.querySelector("[data-wf-run-approval]")).toBeNull();
  //: 列表紧跟头部,而且是它自己那条 `border-t` 顶着 —— 没有一条留给不存在的那一段。
  const header = aside.querySelector("[data-wf-run-history-header]") as HTMLElement;
  const list = aside.querySelector("[data-wf-run-history-list]") as HTMLElement;
  expect(header.nextElementSibling).toBe(list);
  expect(list.className).toContain("border-t");
});

it("待批正文很长时:「确认 / 拒绝」在正文之外,结构上不会被正文推走", async () => {
  //: 真浏览器里的命中测试见验收(`elementFromPoint` + 面板拖到 380px);jsdom 没有排版,
  //: 这里钉住让那一幕成立的结构:正文限高自己滚、按钮是它的**兄弟**而不是子节点。
  seed([SUCCESS_RUN], { approvals: [approval({ body: "很长的稿子。".repeat(4000) })], events: STEP_EVENTS });
  renderHistory();

  await screen.findByText("要按这一版发布吗？");
  const body = document.querySelector("[data-wf-run-approval-body]") as HTMLElement;
  expect(body.className).toContain("max-h-[min(24rem,40vh)]");
  expect(body.className).toContain("overflow-y-auto");
  //: 正文这一块不许再画边(那是第二层框)。
  expect(body.className.includes("border")).toBe(false);

  const actions = document.querySelector("[data-wf-run-approval-actions]") as HTMLElement;
  expect(body.contains(actions), "按钮不能在正文里面跟着滚").toBe(false);
  //: 按钮行是正文之后的下一个兄弟块,右对齐。
  expect(body.compareDocumentPosition(actions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(actions.className).toContain("justify-end");
  expect(actions.contains(screen.getByRole("button", { name: "确认发布" }))).toBe(true);
  expect(actions.contains(screen.getByRole("button", { name: "先别发" }))).toBe(true);
});
