/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 「这一步在等你确认」—— 应用内那一格(见 backend ADR 0064)。
 *
 * 它证的是:停在 `await_approval` 上的一次运行在运行历史里**看得见、点得动**,而且点下去发的是
 * 后端那条和飞书共用的决定接口(POST /api/run-approvals/{id}/decide)——
 * 应用内和飞书不是两套决定。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      runApprovalHeading: "这一步在等你确认",
      runApprovalWaiting: "这一次运行停在「{node}」,确认之后从这里接着跑",
      runApprovalExpires: "超过 {time} 没人处理,就按这个节点上写的办。",
      runApprovalNoExpiry: "不设超时,一直等。",
      runApprovalNotePlaceholder: "备注(可留空)",
      runApprovalSending: "正在提交…",
      runApprovalDone: "已{decision}:那次运行接着往下跑了",
      runApprovalFailed: "没能批下去",
      runApprovalGone: "这次等待已经不在了。",
      runApprovalFeishuHint: "在飞书里点那张卡片也一样。",
      runApprovalDeliverySent: "已发到飞书",
      runApprovalDeliveryStationOnly: "仅站内",
      runApprovalNotDelivered: "这次没能发到飞书,只能在站内批。",
      runApprovalReasonNone: "节点上写的就是「仅站内」",
      runApprovalReasonNoBot: "这个工作区还没有可用的飞书机器人",
      runApprovalReasonNoOrigin: "这次运行不是从飞书来的,发起人也没绑飞书",
      runApprovalReasonNotBound: "节点上点名的那个人没绑飞书账号",
      runApprovalReasonNoTarget: "节点上没说清发给谁",
      runApprovalReasonUnknown: "说不清是为什么",
      runApprovalApproved: "确认",
      runApprovalRejected: "拒绝",
    })[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { RunApprovalNotice } from "@/features/workflows/RunApprovalNotice";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  cleanup();
});

const calls: Array<{ path: string; method: string; body: string }> = [];

/** `holdPost` 那一档把 POST 挂住,这里放着"放行"它的把手。 */
let releasePost: (() => void) | null = null;

function renderNotice(rows: unknown[], opts: { holdPost?: boolean } = {}) {
  calls.length = 0;
  releasePost = null;
  //: `holdPost`:让那一次 POST **挂住不返回** —— 用来观察"提交中"的样子(见下面那条用例)。
  const held = opts.holdPost
    ? new Promise<void>((resolve) => {
        releasePost = resolve;
      })
    : null;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    if (init?.method === "POST") {
      calls.push({ path: url.pathname, method: "POST", body: String(init.body ?? "") });
      if (held) await held;
      const decided = { ...(rows[0] as object), status: "approved", decision: "approved" };
      return new Response(JSON.stringify(decided), { status: 200, headers: { "content-type": "application/json" } });
    }
    const body = url.pathname === "/api/workflows/wf-1/run-approvals" ? rows : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RunApprovalNotice workflowId="wf-1" />
    </QueryClientProvider>,
  );
}

const row = {
  id: "ap-1",
  job_id: "job-1",
  workflow_id: "wf-1",
  node_id: "gate",
  node_name: "上线前确认",
  title: "要发布吗",
  body: "确认之后往下走",
  approve_label: "确认发布",
  reject_label: "先别发",
  allow_note: true,
  status: "pending",
  decision: "",
  //: 默认这一条是**真发到过飞书**的(旧用例按"两条路都能点"写)。
  feishu_delivery: "sent",
  feishu_delivery_reason: "",
  expires_at: null,
  created_at: "2026-10-16T09:00:00",
};

describe("运行停在等人确认上", () => {
  it("说清停在哪一步,按钮用节点上写的文案", async () => {
    renderNotice([row]);
    expect(await screen.findByText("要发布吗")).toBeInTheDocument();
    expect(screen.getByText("这一次运行停在「上线前确认」,确认之后从这里接着跑")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认发布" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "先别发" })).toBeInTheDocument();
  });

  it("点确认:发的是和飞书共用的那条决定接口,备注一起带上", async () => {
    renderNotice([row]);
    fireEvent.change(await screen.findByPlaceholderText("备注(可留空)"), { target: { value: "可以发" } });
    fireEvent.click(screen.getByRole("button", { name: "确认发布" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].path).toBe("/api/run-approvals/ap-1/decide");
    expect(JSON.parse(calls[0].body)).toEqual({ decision: "approved", note: "可以发" });
  });

  it("点拒绝:同一个入口,决定是 rejected", async () => {
    renderNotice([row]);
    fireEvent.click(await screen.findByRole("button", { name: "先别发" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(JSON.parse(calls[0].body)).toEqual({ decision: "rejected", note: "" });
  });

  it("提交中:转圈的只有**点下去的那一颗**,另一颗只是禁用", async () => {
    //: 此前两颗按钮都吃同一个 `decide.isPending` -> 点「拒绝」两个一起转,看起来像**两个决定都在提交**。
    renderNotice([row], { holdPost: true });
    fireEvent.click(await screen.findByRole("button", { name: "先别发" }));

    const rejected = screen.getByRole("button", { name: "先别发" });
    const approved = screen.getByRole("button", { name: "确认发布" });
    await waitFor(() => expect(rejected).toHaveAttribute("aria-busy", "true"));
    expect(approved).not.toHaveAttribute("aria-busy");
    expect(approved).toBeDisabled();

    //: 收尾:把那一次 POST 放行,免得留下悬着的 promise。
    releasePost?.();
    await waitFor(() => expect(calls).toHaveLength(1));
  });

  it("节点关掉了备注那一格:不给输入框", async () => {
    renderNotice([{ ...row, allow_note: false }]);
    await screen.findByText("要发布吗");
    expect(screen.queryByPlaceholderText("备注(可留空)")).toBeNull();
  });

  it("没有人在等:什么都不说", async () => {
    renderNotice([]);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    await waitFor(() => expect(document.querySelector("[data-wf-run-approval]")).toBeNull());
  });

  it("超时那一句只在有 expires_at 时说,没有就说「一直等」", async () => {
    renderNotice([{ ...row, id: "ap-2", expires_at: null }]);
    const notice = await screen.findByText("要发布吗");
    expect(within(notice.closest("[data-wf-run-approval]") as HTMLElement).getByText("不设超时,一直等。")).toBeInTheDocument();
  });

  // ---- 这一次到底发到飞书没有(见后端 domain/workflows/approvals 的 feishu_delivery)----
  //
  // 「在飞书里点那张卡也一样」这句话**只有真发出去过时才成立**。此前卡上根本不提这件事:
  // 传输失败时用户在飞书群里等一张永远不来的卡,而界面上还在说"去飞书点"。

  it("发到过:说已发,并照旧说「在飞书里点那张卡也一样」", async () => {
    renderNotice([row]);
    await screen.findByText("要发布吗");
    expect(screen.getByText("已发到飞书")).toBeInTheDocument();
    expect(screen.getByText("在飞书里点那张卡片也一样。")).toBeInTheDocument();
  });

  it("发失败了:说清只能在站内批、把原因带上,并且不再叫人去飞书点", async () => {
    renderNotice([{ ...row, feishu_delivery: "failed", feishu_delivery_reason: "飞书发卡片失败: connection reset" }]);
    await screen.findByText("要发布吗");
    expect(
      screen.getByText("这次没能发到飞书,只能在站内批。(飞书发卡片失败: connection reset)"),
    ).toBeInTheDocument();
    //: 上面那句已经说清了,别再补一句"去飞书点"。
    expect(screen.queryByText("在飞书里点那张卡片也一样。")).toBeNull();
    //: 这一行按警告的样子出(不是灰字)—— 它是"你要知道"的那一类。
    expect(screen.getByText(/这次没能发到飞书/).className).toContain("text-warning");
  });

  it("仅站内:说清是节点上写的那一档,不是失败", async () => {
    renderNotice([{ ...row, feishu_delivery: "not_attempted", feishu_delivery_reason: "none" }]);
    await screen.findByText("要发布吗");
    expect(screen.getByText("仅站内 · 节点上写的就是「仅站内」")).toBeInTheDocument();
    expect(screen.queryByText("在飞书里点那张卡片也一样。")).toBeNull();
  });

  it("没机器人可发:原因换成人话(「no-bot」不给人看)", async () => {
    renderNotice([{ ...row, feishu_delivery: "not_attempted", feishu_delivery_reason: "no-bot" }]);
    await screen.findByText("要发布吗");
    expect(screen.getByText("仅站内 · 这个工作区还没有可用的飞书机器人")).toBeInTheDocument();
  });

  it("这一版之前建的没有投递记录:这件事一个字都不说", async () => {
    renderNotice([{ ...row, feishu_delivery: "", feishu_delivery_reason: "" }]);
    await screen.findByText("要发布吗");
    expect(document.querySelector("[data-wf-run-approval-delivery]")).toBeNull();
    expect(screen.queryByText("在飞书里点那张卡片也一样。")).toBeNull();
  });
});

describe("审批正文很长时", () => {
  it("正文自己滚、有高度上限;「确认 / 拒绝」不会被顶出卡外", async () => {
    //: 维护者:「确认卡高度超出后我无法滚动导致我都无法点击同意拒绝」—— 正文原样铺开把按钮推走了。
    renderNotice([{ ...row, body: "很长的稿子。".repeat(400) }]);
    expect(await screen.findByText("要发布吗")).toBeInTheDocument();

    const body = document.querySelector("[data-wf-run-approval-body]") as HTMLElement;
    expect(body, "正文该有一个上限 + 滚动的容器").toBeTruthy();
    //: 上限和纵向滚动两样都要:只给上限是截断,只给滚动不生效。
    expect(body.className).toContain("overflow-y-auto");
    expect(body.className).toMatch(/max-h-\[/);
    //: 按钮在正文**外面**,不跟着一起滚走。
    expect(body.contains(screen.getByRole("button", { name: "确认发布" }))).toBe(false);
  });
});
