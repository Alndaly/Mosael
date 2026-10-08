/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 确认卡是智能体写操作与执行之间唯一的闸,所以「哪一个在转」必须指向**你刚点的那一个**。
 *
 * 三个按钮共用一个 mutation 的 isPending,于是点「允许一次」时三个一起转 —— 而且同屏有第二张
 * 卡时,那张卡的三个也一起转。转圈是"我正在做这件事"的意思;六个一起转说的是另一件事,而在
 * 一张需要知情同意的卡上,这个歧义正好落在最不该有歧义的地方。
 */

const TEMPLATES: Record<string, string> = {
  confirmAllowOnce: "允许一次",
  confirmAllowSession: "本会话始终允许",
  confirmReject: "拒绝",
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEMPLATES[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

vi.mock("@/features/agent/confirmSurface", () => ({ registerInlineConfirmSurface: () => () => {} }));

const pendingCards = [
  { id: "c1", tool: "edit_timeline", allow_tool: "edit_timeline", summary: "改时间线", permission: "edit", payload: {}, status: "pending" },
  { id: "c2", tool: "render_sequence", allow_tool: "render_sequence", summary: "导出", permission: "render-cost", payload: {}, status: "pending" },
  { id: "c3", tool: "run_host_code", allow_tool: "run_host_code", summary: "⚠️ **不隔离**,直接在你的电脑上运行", permission: "external", payload: {}, status: "pending" },
  {
    id: "c4", tool: "run_plugin_tool", allow_tool: "plugin__conn__wf_portrait", summary: "跑「人像」", permission: "ai-cost",
    payload: {}, status: "pending",
  },
];

/** 决策请求停在这里,好在"正在飞"的那一刻断言。 */
let releaseDecision: () => void = () => {};

const api = vi.fn(async (path: string, _init?: unknown) => {
  if (path.startsWith("/api/confirmations?")) return pendingCards;
  if (path.startsWith("/api/agent/questions")) return [];
  if (path.startsWith("/api/agent/sessions/")) return { id: "s1", auto_allow_tools: [] };
  await new Promise<void>((resolve) => {
    releaseDecision = resolve;
  });
  return { ...pendingCards[0], status: "failed", error: "磁盘满了" };
});

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()), api: (path: string, init?: unknown) => api(path, init) }));

import { PendingDecisions, SessionDecisions } from "@/features/agent/PendingDecisions";

/** 对话里没有任何一行对得上这几张卡(夹具的卡不带 tool_call_id):它们全摆在列表末尾那一叠里。 */
function renderCards({ readOnly = false }: { readOnly?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionDecisions workspaceId="w1" sessionId="s1" readOnly={readOnly}>
        <PendingDecisions placed={new Set()} />
      </SessionDecisions>
    </QueryClientProvider>,
  );
}

/** 转圈的按钮 —— Button 在 loading 时置 aria-busy。 */
function busyLabels(container: HTMLElement): string[] {
  return [...container.querySelectorAll("button[aria-busy]")].map((node) => node.textContent?.trim() ?? "");
}

describe("确认卡的等待状态", () => {
  beforeEach(() => {
    api.mockClear();
  });

  it("只有被点的那个按钮转圈", async () => {
    const { container } = renderCards();
    const buttons = await screen.findAllByText("允许一次");

    buttons[0].click();

    await waitFor(() => expect(busyLabels(container).length).toBeGreaterThan(0));
    expect(busyLabels(container)).toEqual(["允许一次"]);
    releaseDecision();
  });

  it("同一张卡的另外两个禁掉,但不转圈 —— 一张卡只能有一个结论", async () => {
    const { container } = renderCards();
    (await screen.findAllByText("允许一次"))[0].click();

    await waitFor(() => expect(busyLabels(container).length).toBe(1));
    const card = container.querySelectorAll("article")[0];
    const disabled = [...card.querySelectorAll("button")].filter((node) => node.hasAttribute("disabled"));
    expect(disabled.length).toBe(3); //: 第一张是 edit,三档都在
    releaseDecision();
  });

  it("另一张卡完全不受影响 —— 它等的不是同一件事", async () => {
    const { container } = renderCards();
    (await screen.findAllByText("允许一次"))[0].click();

    await waitFor(() => expect(busyLabels(container).length).toBe(1));
    const second = container.querySelectorAll("article")[1];
    expect([...second.querySelectorAll("button")].some((node) => node.hasAttribute("disabled"))).toBe(false);
    releaseDecision();
  });

  it("「本会话始终允许」要写白名单再批准,整段都转它自己那一个", async () => {
    const { container } = renderCards();
    (await screen.findAllByText("本会话始终允许"))[0].click();

    // 第一步(写白名单)与第二步(批准)之间不能换一个按钮转 —— 用户看到的是同一个动作。
    await waitFor(() => expect(busyLabels(container).length).toBe(1));
    expect(busyLabels(container)).toEqual(["本会话始终允许"]);
    releaseDecision();
  });

  it("「本会话始终允许」记下的是(工具, 这张卡的档位),不只是工具名", async () => {
    /* 只记工具名时,点过一张 ai-cost 的 run_workflow,之后带 HTTP / 发布节点(external)的 run_workflow 也直接放行。 */
    renderCards();
    (await screen.findAllByText("本会话始终允许"))[1].click();
    await waitFor(() =>
      expect(api.mock.calls.some(([path, init]) => path === "/api/agent/sessions/s1" && (init as RequestInit)?.method === "PATCH")).toBe(true),
    );
    const [, init] = api.mock.calls.find(([path, init]) => path === "/api/agent/sessions/s1" && (init as RequestInit)?.method === "PATCH")!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      auto_allow_tools: [{ tool: "render_sequence", permission: "render-cost" }],
    });
    releaseDecision();
  });

  it("替别的工具开的卡(run_plugin_tool),「本会话始终允许」记在卡说的那个工具名下 —— 只放行同一张工作流", async () => {
    renderCards();
    // c3 是撤不回的那一档,没有这个按钮:第三个「本会话始终允许」是 c4 的。
    (await screen.findAllByText("本会话始终允许"))[2].click();
    await waitFor(() =>
      expect(api.mock.calls.some(([path, init]) => path === "/api/agent/sessions/s1" && (init as RequestInit)?.method === "PATCH")).toBe(true),
    );
    const [, init] = api.mock.calls.find(([path, init]) => path === "/api/agent/sessions/s1" && (init as RequestInit)?.method === "PATCH")!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      auto_allow_tools: [{ tool: "plugin__conn__wf_portrait", permission: "ai-cost" }],
    });
    releaseDecision();
  });

  it("撤不回的那一档不给「本会话始终允许」,并说一句为什么", async () => {
    const { container } = renderCards();
    await screen.findAllByText("允许一次");
    const external = container.querySelectorAll("article")[2];
    expect(external.textContent).not.toContain("本会话始终允许");
    expect(external.textContent).toContain("confirmAsksEveryTime");
    expect(external.textContent).toContain("允许一次");
    const edit = container.querySelectorAll("article")[0];
    expect(edit.textContent).toContain("本会话始终允许");
    expect(edit.textContent).not.toContain("confirmAsksEveryTime");
  });
});

it("拍板之后卡就离开这一叠 —— 待决列表还没刷新也不再画它", async () => {
  /* 此前有了结论的卡留成一张「✓ 已执行 / 执行失败」加 ×,要人手动关(用户:「审批通过后那个卡片不需要继续保留着的」)。
     结果(连同失败原因)现在收在那次工具调用的一行里,见 CanvasAgentChat.decisions.dom.test。 */
  const { container } = renderCards();
  (await screen.findAllByText("允许一次"))[0].click();
  await waitFor(() => expect(busyLabels(container).length).toBe(1));
  releaseDecision();

  //: 夹具的待决列表一直把 c1 当待决返回 —— 自己刚拍板的那一份走得更远,以它为准。
  await waitFor(() => expect(container.querySelectorAll("article")).toHaveLength(pendingCards.length - 1));
  expect(container.querySelector("article[data-status='failed']")).toBeNull();
  expect(screen.queryByRole("button", { name: "confirmDismiss" })).toBeNull();
});

it("权限徽标不跟着长摘要换行 —— 两个字被压成一列竖排就没法读了", async () => {
  /* 摘要可以很长(「3 个工作流编辑: set_node_config, set_node_config, set_node_config」),
     它和徽标同在一个 flex 行里。两边都可缩时,浏览器挑徽标下手:「编辑」竖排成两行。
     jsdom 没有排版,能钉的是那两个决定它不被挤的类落在了徽标自己身上。 */
  renderCards();
  const badge = (await screen.findAllByText("permEdit"))[0]; //: 这份夹具的 i18n 原样吐 key
  expect(badge.className).toContain("shrink-0");
  expect(badge.className).toContain("whitespace-nowrap");
});

it("摘要里的 **强调** 渲染成粗体 —— 这是用户批准前唯一会读的那一行", async () => {
  const { container } = renderCards();
  expect((await screen.findByText("不隔离")).tagName).toBe("STRONG");
  expect(container.textContent).not.toContain("**");
});

it("同事共享来的对话:卡照样看得见,三档动作换成「等主人拍板」", async () => {
  renderCards({ readOnly: true });
  expect(await screen.findByText("改时间线")).toBeTruthy();
  expect(screen.getAllByText("agentDecisionOwnerOnly")).toHaveLength(pendingCards.length);
  expect(screen.queryByRole("button", { name: /允许一次|本会话始终允许|拒绝/ })).toBeNull();
});
