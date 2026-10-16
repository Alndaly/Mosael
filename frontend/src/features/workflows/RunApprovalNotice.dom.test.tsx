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
});
