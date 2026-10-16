/** @vitest-environment jsdom */
/**
 * 触发器面板的 dom 测试:**列出来、能关掉、能新建(含入参映射)、看得见它在干活**。
 *
 * `t` 在这里是恒等函数(文案表有自己的棘轮,见 app/messages.test.ts),所以断言里出现的是键名。
 * 这样断言的是"这一格用了哪个键、递了什么请求",而不是某一句中文 —— 改文案不会弄红它。
 */
import React from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: toasts.success, error: toasts.error } }));
vi.mock("@/app/preferences", () => ({
  usePreferences: () => ({ t: (key: string) => key }),
  useI18n: () => (key: string) => key,
}));

//: 触发器那一族的接口。**界面不自己拼路径**(棘轮 design/apiSeam),所以这里按函数名换,不按路径。
const triggers = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  events: vi.fn(),
}));
vi.mock("@/api/client", () => ({
  listWorkflowTriggers: triggers.list,
  createWorkflowTrigger: triggers.create,
  updateWorkflowTrigger: triggers.update,
  deleteWorkflowTrigger: triggers.remove,
  listWorkflowTriggerEvents: triggers.events,
}));

//: 面板还要拉机器人清单(那一条还没进 api/domains,走 transport)。
const api = vi.hoisted(() => ({ call: vi.fn() }));
vi.mock("@/api/transport", () => ({ api: api.call }));

import { WorkflowTriggersDialog } from "./WorkflowTriggersDialog";

beforeAll(() => {
  // Radix 的 Select / Dialog 在 jsdom 里要这几样。
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

const WORKFLOW = {
  id: "wf1",
  name: "视频转码",
  graph: { nodes: [{ id: "start", type: "start", config: { params: { asset_id: "", text: "" } } }], edges: [] },
};

const TRIGGER = {
  id: "tr1",
  workspace_id: "ws1",
  workflow_id: "wf1",
  name: "群里的视频",
  bot_id: "",
  chat_id: "oc_1",
  message_types: ["media", "text"],
  keywords: [],
  only_from_open_ids: [],
  params: { asset_id: "{{trigger.asset_id}}" },
  reply_in_chat: true,
  max_runs_per_minute: 6,
  enabled: true,
  last_fired_at: "2026-10-16T02:00:00",
  created_at: "2026-10-15T02:00:00",
};

const EVENT = {
  id: "ev1",
  message_id: "om_9",
  message_type: "media",
  text_preview: "这个视频帮我转一下",
  asset_ids: ["a1"],
  job_id: "job1",
  status: "started",
  error: "",
  created_at: "2026-10-16T02:00:00",
};

const REFUSED = {
  ...EVENT,
  id: "ev2",
  message_id: "om_10",
  text_preview: "第二条",
  job_id: null,
  status: "refused",
  error: "工作流「视频转码」跑不起来:缺少必填:asset_id",
};

/** 表单是同一个弹窗里换出来的一段(不是新开的 Dialog),按属性找它比按 data-testid 更贴仓库的习惯。 */
async function waitForForm(): Promise<HTMLElement> {
  return waitFor(() => {
    const found = document.querySelector("[data-workflow-trigger-form]");
    if (!found) throw new Error("trigger form not rendered yet");
    return found as HTMLElement;
  });
}

function setup(canEdit = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WorkflowTriggersDialog workspaceId="ws1" workflow={WORKFLOW} open canEdit={canEdit} onOpenChange={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.call.mockResolvedValue([{ id: "bot1", name: "Mosael 助手" }]);
  triggers.list.mockResolvedValue([TRIGGER]);
  triggers.events.mockResolvedValue([EVENT]);
  triggers.create.mockResolvedValue(TRIGGER);
  triggers.update.mockResolvedValue({ ...TRIGGER, enabled: false });
  triggers.remove.mockResolvedValue(undefined);
});
afterEach(cleanup);

it("列出手上这条工作流的触发器,并说清它认什么、上次什么时候触发的", async () => {
  setup();
  expect(await screen.findByText("群里的视频")).toBeInTheDocument();
  // 摘要那一行:认哪些消息 · 机器人/群 · 限流。
  expect(screen.getByText(/workflowTriggersTypeMedia/)).toBeInTheDocument();
  expect(screen.getByText(/oc_1/)).toBeInTheDocument();
  expect(screen.getByText(/workflowTriggersLastFired/)).toBeInTheDocument();
});

it("点开关就是停用它(不是只管界面)", async () => {
  const user = userEvent.setup();
  setup();
  const row = await screen.findByText("群里的视频");
  const card = row.closest("[data-workflow-trigger]") as HTMLElement;
  await user.click(within(card).getByRole("switch", { name: "群里的视频" }));
  await waitFor(() => expect(triggers.update).toHaveBeenCalledWith("tr1", { enabled: false }));
});

it("最近触发看得见:哪条消息、什么结果、哪次运行", async () => {
  const user = userEvent.setup();
  setup();
  const row = await screen.findByText("群里的视频");
  const card = row.closest("[data-workflow-trigger]") as HTMLElement;
  await user.click(within(card).getByRole("button", { name: /workflowTriggersRecent/ }));
  expect(await screen.findByText(/这个视频帮我转一下/)).toBeInTheDocument();
  expect(screen.getByText("workflowTriggersStatusStarted")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /workflowTriggersOpenRun/ })).toBeInTheDocument();
});

it("没跑起来的那一条把原因摆出来(走全应用那份失败卡)", async () => {
  const user = userEvent.setup();
  triggers.events.mockResolvedValue([REFUSED]);
  setup();
  const row = await screen.findByText("群里的视频");
  const card = row.closest("[data-workflow-trigger]") as HTMLElement;
  await user.click(within(card).getByRole("button", { name: /workflowTriggersRecent/ }));
  const failure = await waitFor(() => {
    const found = document.querySelector("[data-failure]");
    if (!found) throw new Error("failure card not rendered yet");
    return found as HTMLElement;
  });
  expect(failure.textContent).toContain("缺少必填:asset_id");
});

it("只读成员看得到最近触发,但没有开关和新建", async () => {
  setup(false);
  await screen.findByText("群里的视频");
  expect(screen.queryByRole("button", { name: /workflowTriggersAdd/ })).toBeNull();
  expect(screen.getByRole("switch", { name: "群里的视频" })).toBeDisabled();
});

it("新建:选消息类型、把某一格消息字段映射到开始节点的参数、保存", async () => {
  const user = userEvent.setup();
  setup();
  await screen.findByText("群里的视频");
  await user.click(screen.getByRole("button", { name: /workflowTriggersAdd/ }));

  const form = await waitForForm();
  await user.type(within(form).getByPlaceholderText("workflowTriggersNamePlaceholder"), "群里的视频");

  // 「认哪些消息」:默认只有文字,再加上视频。
  await user.click(within(form).getByRole("button", { name: "workflowTriggersTypeMedia" }));

  // 入参:把 asset_id 这一格映射到「素材(第一份)」。
  await user.click(within(form).getByRole("combobox", { name: "asset_id" }));
  await user.click(await screen.findByRole("option", { name: "workflowTriggersFieldAsset" }));

  await user.click(within(form).getByRole("button", { name: "save" }));

  await waitFor(() =>
    expect(triggers.create).toHaveBeenCalledWith({
      workspace_id: "ws1",
      workflow_id: "wf1",
      name: "群里的视频",
      bot_id: "",
      chat_id: "",
      message_types: ["text", "media"],
      keywords: [],
      params: { asset_id: "{{trigger.asset_id}}" },
      reply_in_chat: true,
      max_runs_per_minute: 6,
    }),
  );
});

it("删除要人确认一次 —— 确认键写的是动作本身", async () => {
  const user = userEvent.setup();
  setup();
  const row = await screen.findByText("群里的视频");
  const card = row.closest("[data-workflow-trigger]") as HTMLElement;
  await user.click(within(card).getByRole("button", { name: "workflowTriggersDelete: 群里的视频" }));
  expect(await screen.findByText("workflowTriggersDeleteConfirm")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "delete" }));
  await waitFor(() => expect(triggers.remove).toHaveBeenCalledWith("tr1"));
});

it("开始节点没有参数时说清没有可映射的", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowTriggersDialog
        workspaceId="ws1"
        workflow={{ id: "wf1", name: "视频转码", graph: { nodes: [{ id: "s", type: "start", config: { params: {} } }], edges: [] } }}
        open
        onOpenChange={() => {}}
      />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await screen.findByText("群里的视频");
  await user.click(screen.getByRole("button", { name: /workflowTriggersAdd/ }));
  const form = await waitForForm();
  expect(within(form).getByText("workflowTriggersNoParams")).toBeInTheDocument();
});
