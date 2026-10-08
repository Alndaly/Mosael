/** @vitest-environment jsdom */
/**
 * 定时任务页这一组修(体检 UM-02 / UM-03 / UM-18,和安全那一路的 SEC-1 / SEC-2):
 * - 新建任务要填工作流开始节点的必填参数,没填不发请求;带上这台电脑的时区;
 * - 触发密钥只在生成的那一次看得到,之后是遮住的;只存哈希之前的那把提醒主人重置;
 * - 别人的任务:运行、启停、删除、改参数都动不了,说清为什么;
 * - 运行记录的时间按本地时区显示,不是截后端的 UTC 字符串。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const h = vi.hoisted(() => ({
  tasks: [] as any[],
  runs: [] as any[],
  create: vi.fn(),
  update: vi.fn(),
  attest: vi.fn(),
}));

const WORKFLOW = {
  id: "wf1",
  workspace_id: "w1",
  name: "商品图",
  description: "",
  revision: 1,
  graph_hash: "",
  created_at: "2026-10-01T00:00:00",
  updated_at: "2026-10-01T00:00:00",
  graph: {
    nodes: [
      {
        id: "start",
        type: "start",
        config: { params: { product_name: "", scene_count: 4 }, required_params: ["product_name"] },
      },
    ],
    edges: [],
  },
};

function task(overrides: Record<string, unknown> = {}) {
  return {
    id: "t1",
    workspace_id: "w1",
    project_id: null,
    name: "每天出图",
    kind: "workflow",
    trigger_type: "webhook",
    schedule: {},
    timezone: "UTC",
    enabled: true,
    payload: { workflow_id: "wf1", params: { product_name: "开衫" } },
    next_run_at: null,
    last_run_at: null,
    created_at: "2026-10-01T00:00:00",
    updated_at: "2026-10-01T00:00:00",
    owner_user_id: "me",
    is_mine: true,
    shared: true,
    webhook_secret_set_at: "2026-10-01T00:00:00",
    webhook_secret: null,
    ...overrides,
  };
}

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  API_BASE: "http://127.0.0.1:8800",
  listScheduledTasks: async () => h.tasks,
  listWorkflows: async () => [WORKFLOW],
  listScheduledTaskRuns: async () => h.runs,
  createScheduledTask: h.create,
  updateScheduledTask: h.update,
  deleteScheduledTask: vi.fn(),
  runScheduledTask: vi.fn(),
  resetWebhookSecret: vi.fn(),
  setResourceShared: vi.fn(),
  attestWorkflowRevision: h.attest,
  fetchJobKinds: async () => ({ kinds: [], fallback: { kind: "", label: "任务", announce: "never", affects: [], view: null, record_field: null } }),
  topLevelJobsQuery: (workspaceId: string) => ({ queryKey: ["jobs", workspaceId, "top-level"], queryFn: async () => [] }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { SchedulerView } from "./SchedulerView";
import { readHint } from "@/test/hint";

function mount(role = "owner") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <SchedulerView workspace={{ id: "w1", name: "W", role } as never} project={null} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  // 工作流下拉(cmdk)挂载时要 ResizeObserver,jsdom 没有。
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView ??= () => {};
  h.tasks = [];
  h.runs = [];
  h.create.mockReset();
  h.update.mockReset();
  localStorage.clear();
});

describe("新建定时任务", () => {
  it("要填工作流的必填参数:没填不发请求、说出缺哪项;填了带着参数和本地时区建", async () => {
    h.create.mockImplementation(async (body: any) => task({ ...body, id: "t2", webhook_secret: null, trigger_type: body.trigger_type }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: /createTask/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getAllByRole("combobox")[0]);
    fireEvent.click(await screen.findByText("商品图"));

    const field = await within(dialog).findByRole("textbox", { name: "product_name *" });
    expect(within(dialog).getByRole("textbox", { name: "scene_count" }).getAttribute("placeholder")).toBe("taskParamDefaultPlaceholder");
    const submit = within(dialog).getAllByRole("button", { name: /createTask/ }).at(-1)!;
    fireEvent.click(submit);
    expect(await within(dialog).findByText("taskParamMissing")).toBeTruthy();
    expect(h.create).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: "羊毛开衫" } });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "scene_count" }), { target: { value: "6" } });
    fireEvent.click(submit);
    await waitFor(() => expect(h.create).toHaveBeenCalledTimes(1));
    const body = h.create.mock.calls[0][0];
    expect(body.payload).toEqual({ workflow_id: "wf1", params: { product_name: "羊毛开衫", scene_count: 6 } });
    expect(body.timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
  });

  it("建 webhook 任务回来的密钥原文当场显示一次", async () => {
    h.create.mockImplementation(async () => {
      const created = task({ id: "t9", webhook_secret: "s3cret-once" });
      h.tasks = [{ ...created, webhook_secret: null }];
      return created;
    });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: /createTask/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getAllByRole("combobox")[0]);
    fireEvent.click(await screen.findByText("商品图"));
    fireEvent.change(await within(dialog).findByRole("textbox", { name: "product_name *" }), { target: { value: "x" } });
    fireEvent.click(within(dialog).getAllByRole("button", { name: /createTask/ }).at(-1)!);

    await waitFor(() => expect(document.body.textContent).toContain("?secret=s3cret-once"));
    expect(document.querySelector("[data-webhook-secret-once]")).toBeTruthy();
  });
});

describe("任务详情", () => {
  it("密钥是遮住的;只存哈希之前的那把提醒主人重置", async () => {
    h.tasks = [task({ webhook_secret_set_at: null })];
    mount();
    await screen.findByText("webhookUrlLabel");
    expect(document.body.textContent).toContain("?secret=••••••");
    expect(document.querySelector("[data-webhook-secret-legacy]")?.textContent).toContain("webhookLegacySecret");
  });

  it("别人的任务:运行、启停、删除、改参数都动不了", async () => {
    h.tasks = [task({ is_mine: false, owner_user_id: "someone" })];
    mount();
    const run = await screen.findByRole("button", { name: /runNow/ });
    await waitFor(() => expect(run.hasAttribute("disabled")).toBe(true));
    expect(screen.getByRole("switch").hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: /^delete$/ }).hasAttribute("disabled")).toBe(true);
    expect((await screen.findByRole("button", { name: "taskParamsEdit" })).hasAttribute("disabled")).toBe(true);
    expect(document.querySelector("[data-webhook-secret-legacy]")).toBeNull();
  });

  it("运行记录按本地时区显示时间;每天几点的任务说清按哪个时区", async () => {
    h.tasks = [task({ trigger_type: "daily", schedule: { time: "09:00" }, timezone: "Etc/GMT+12" })];
    h.runs = [{ id: "r1", scheduled_task_id: "t1", job_id: null, status: "succeeded", result: {}, error: null, started_at: "2026-09-24T08:58:17", finished_at: "2026-09-24T08:58:20" }];
    mount();
    const expected = new Date("2026-09-24T08:58:17Z").toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    });
    await waitFor(() => expect(document.body.textContent).toContain(expected));
    expect(document.querySelector("[data-task-timezone]")?.textContent).toContain("taskTimezoneOther");
    fireEvent.click(screen.getByRole("button", { name: "taskTimezoneUseLocal" }));
    await waitFor(() =>
      expect(h.update).toHaveBeenCalledWith("t1", { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }),
    );
  });

  //: 体检 UM-20 / UM-25:只读成员此前看得到「新建任务」,点了收到一句英文 403;页面标题叫「任务」,和任务中心撞名。
  it("只读成员的「新建任务」灰掉并说为什么;标题叫「定时任务」", async () => {
    mount("viewer");
    const create = await screen.findByRole("button", { name: /createTask/ });
    expect(create.hasAttribute("disabled")).toBe(true);
    expect(await readHint(create)).toBe("roleReadOnlyHint");
    expect(screen.getByRole("heading", { level: 2, name: "schedulerTitle" })).toBeTruthy();
  });
});

//: ADR 0047:绑着的图是别人改的,下一次到点要等主人认可、不花主人的 AI 连接。列表和详情上都看得见,主人就地认可。
describe("待你确认", () => {
  const waiting = { workflow_id: "wf1", workflow_name: "商品图", revision: 7 };

  it("我的任务:列表上标「待你确认」,详情里说清是哪一版,点「认可这一版」认可的就是它", async () => {
    h.attest.mockResolvedValue({});
    h.tasks = [task({ awaiting_approval: waiting })];
    mount();
    const notice = await waitFor(() => {
      const found = document.querySelector("[data-task-awaiting-approval]");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(notice.textContent).toContain("taskAwaitingApproval");
    expect(notice.textContent).toContain("taskAwaitingApprovalBody");
    expect(document.querySelector("[data-task-awaiting-approval-mark]")?.textContent).toContain("taskAwaitingApproval");
    h.tasks = [task({ awaiting_approval: null })];
    fireEvent.click(within(notice).getByRole("button", { name: /wfRevisionAttestFor/ }));
    await waitFor(() => expect(h.attest).toHaveBeenCalledWith("wf1", 7));
    //: 认可之后任务重新拉一遍,标记跟着消失。
    await waitFor(() => expect(document.querySelector("[data-task-awaiting-approval]")).toBeNull());
  });

  it("别人的任务:说在等主人,不给认可按钮 —— 花的不是我的钱", async () => {
    h.tasks = [task({ is_mine: false, owner_user_id: "someone", awaiting_approval: waiting })];
    mount();
    const notice = await waitFor(() => {
      const found = document.querySelector("[data-task-awaiting-approval]");
      expect(found).not.toBeNull();
      return found as HTMLElement;
    });
    expect(notice.textContent).toContain("taskAwaitingApprovalOther");
    expect(notice.textContent).toContain("taskAwaitingApprovalBodyOther");
    expect(within(notice).queryByRole("button")).toBeNull();
    expect(document.querySelector("[data-task-awaiting-approval-mark]")?.textContent).toContain("taskAwaitingApprovalOther");
  });

  it("不在等:什么都不挂", async () => {
    h.tasks = [task({ awaiting_approval: null })];
    mount();
    await screen.findByRole("button", { name: /runNow/ });
    expect(document.querySelector("[data-task-awaiting-approval]")).toBeNull();
    expect(document.querySelector("[data-task-awaiting-approval-mark]")).toBeNull();
  });
});
