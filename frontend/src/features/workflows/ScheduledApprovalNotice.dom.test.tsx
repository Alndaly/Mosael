/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 别人的定时任务绑着这张图、在等主人认可改过的那一版(ADR 0047 D10):编辑器顶上说一声 —— 只提醒、不拦。
 * 改图的人看到要谁认可;主人自己打开时就地「认可这一版」,认可的是任务在等的那一版(可能是子流程的)。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      wfAwaitingYourApproval: "你的「{task}」在等你认可「{workflow}」v{version}",
      wfAwaitingOwnerApproval: "{owner} 的「{task}」要 {owner} 认可",
    })[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { TooltipProvider } from "@/components/ui/tooltip";
import { ScheduledApprovalNotice } from "@/features/workflows/ScheduledApprovalNotice";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  cleanup();
});

const posted: string[] = [];

function renderNotice(rows: unknown[]) {
  posted.length = 0;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    if (init?.method === "POST") {
      posted.push(url.pathname);
      return new Response(JSON.stringify({}), { status: 200, headers: { "content-type": "application/json" } });
    }
    const body = url.pathname === "/api/workflows/wf-parent/awaiting-approvals" ? rows : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <ScheduledApprovalNotice workflowId="wf-parent" />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

const awaiting = { workflow_id: "wf-child", workflow_name: "子流程", revision: 4 };

describe("绑着这张图的定时任务在等主人认可", () => {
  it("改图的人:说清要谁认可,不给认可按钮", async () => {
    renderNotice([{ task_id: "t1", task_name: "日报", owner_name: "阿青", is_mine: false, awaiting }]);
    expect(await screen.findByText("阿青 的「日报」要 阿青 认可")).toBeInTheDocument();
    const notice = document.querySelector("[data-wf-awaiting-approval]") as HTMLElement;
    expect(within(notice).queryByRole("button")).toBeNull();
  });

  it("主人自己:就地认可的是任务在等的那一版(子流程的),不是这一张的当前版", async () => {
    renderNotice([{ task_id: "t1", task_name: "日报", owner_name: "我", is_mine: true, awaiting }]);
    expect(await screen.findByText("你的「日报」在等你认可「子流程」v4")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /wfRevisionAttestFor/ }));
    await waitFor(() => expect(posted).toEqual(["/api/workflows/wf-child/revisions/4/attest"]));
  });

  it("没有在等的任务:什么都不说", async () => {
    renderNotice([]);
    //: 等清单真的拉回来(空的)再看 —— 不是拉回来之前那一刻的「什么都没有」。
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    await waitFor(() => expect(document.querySelector("[data-wf-awaiting-approval]")).toBeNull());
  });
});
