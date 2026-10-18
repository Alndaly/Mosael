/** @vitest-environment jsdom */
/**
 * 被智能体接住的后台任务回执**不单独占一条消息**:它收进那一轮回答的「已处理 · N 步」里,
 * 默认收起 —— 对话里留的是结论(智能体那句话),回执是那一轮的由头,展开才看。
 *
 * 没被接住的回执不走这里(它们作为独立的一条显式出现,见 JobReceiptNotice):这个组件只收
 * `foldedReceipts`,收谁由调用方按 `receiptWasCaught` 决定。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ getJob: vi.fn(), fetchJobKinds: vi.fn() }));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/api/client", () => ({
  api: vi.fn(async () => ({})),
  getJob: h.getJob,
  fetchJobKinds: h.fetchJobKinds,
  cancelJob: vi.fn(),
  listJobEvents: vi.fn(async () => []),
  listJobChildren: vi.fn(async () => []),
  regenerateAssetProxy: vi.fn(),
}));
vi.mock("@/components/jobs/JobDetailDialog", () => ({
  JobDetailDialog: ({ job }: { job: { id: string } | null }) =>
    job ? <div data-testid="job-detail">{job.id}</div> : null,
}));
vi.mock("streamdown", () => ({
  Streamdown: ({ children }: { children: string }) => <div>{children}</div>,
  CodeBlockCopyButton: () => <button type="button" />,
}));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: () => {} }) }));
vi.mock("@/features/agent/InlineConfirmations", () => ({ PendingConfirmationCard: () => <div data-pending-card="" /> }));
vi.mock("@/features/agent/messageUsage", () => ({
  MessageFooter: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  MessageTime: () => null,
  MessageUsageFooter: () => null,
}));

import { AgentTurnContent } from "@/features/agent/ToolCalls";
import { ChatBubble } from "@/features/agent/ChatBubble";

const CATALOG = {
  kinds: [{ kind: "tts", label: "配音", announce: "always", affects: ["assets"], view: "ai", record_field: "session_id" }],
  fallback: { kind: "", label: "任务", announce: "always", affects: [], view: null, record_field: null },
};

beforeEach(() => {
  h.getJob.mockReset().mockResolvedValue({
    id: "j1", workspace_id: "w1", kind: "tts", status: "succeeded", progress: 1,
    message: "完成", payload: {}, error: null, error_summary: null,
    created_at: "2026-10-18T08:00:00", updated_at: "2026-10-18T08:00:00",
  });
  h.fetchJobKinds.mockReset().mockResolvedValue(CATALOG);
});

const receipt = { id: "r1", payload: { job_id: "j1", kind: "tts", status: "succeeded", subject: "配音 1" } };

function mount(timeline: Parameters<typeof AgentTurnContent>[0]["timeline"], foldedReceipts = [receipt]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AgentTurnContent timeline={timeline} foldedReceipts={foldedReceipts} />
    </QueryClientProvider>,
  );
}

it("接住了的回执收进「已处理 · N 步」,默认收起;展开才看得到,且不另画一张回执卡", async () => {
  const { container } = mount([{ type: "text", text: "配音 1 已经好了" }]);

  const summary = screen.getByRole("button", { name: /agentProcessDone/ });
  expect(summary.getAttribute("aria-expanded")).toBe("false");
  //: 收起时回执那一行不在 DOM 里 —— 对话里只看得到结论。
  expect(container.querySelector("[data-receipt-step]")).toBeNull();
  //: 不是独立的一条回执消息(那会带 data-job-receipt)。
  expect(container.querySelector("[data-job-receipt]")).toBeNull();

  fireEvent.click(summary);
  const step = container.querySelector<HTMLElement>("[data-receipt-step='j1']");
  expect(step).toBeTruthy();
  expect(step?.textContent).toContain("chatJobsTitle");
  expect(step?.textContent).toContain("配音");
  expect(step?.textContent).toContain("配音 1");
  expect(step?.textContent).toContain("runStatus_succeeded");
});

it("点那一行看详情:现取这条任务,打开任务详情", async () => {
  const { container } = mount([{ type: "text", text: "配音 1 已经好了" }]);
  fireEvent.click(screen.getByRole("button", { name: /agentProcessDone/ }));
  fireEvent.click(container.querySelector<HTMLElement>("[data-receipt-step='j1']")!);
  await waitFor(() => expect(h.getJob).toHaveBeenCalledWith("j1"));
  await waitFor(() => expect(screen.getByTestId("job-detail").textContent).toBe("j1"));
});

it("没有回执要收:简短回答不凭空多出一行「已处理 · 1 步」", () => {
  const { container } = mount([{ type: "text", text: "好的" }], []);
  expect(screen.queryByRole("button", { name: /agentProcessDone/ })).toBeNull();
  expect(container.querySelector("[data-turn-receipts]")).toBeNull();
});

it("气泡把收进来的回执转给这一轮(折叠项挂在回答里,不在外面再排一条)", () => {
  const message = {
    id: "a1",
    session_id: "s1",
    role: "assistant",
    content: "配音 1 已经好了",
    payload: { timeline: [{ type: "text", text: "配音 1 已经好了" }] },
    error: null,
    created_at: "2026-10-18T08:00:02",
  } as unknown as Parameters<typeof ChatBubble>[0]["message"];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <ChatBubble message={message} usageEvents={[]} workspaceId="w1" foldedReceipts={[receipt]} />
    </QueryClientProvider>,
  );
  expect(container.querySelector("[data-receipt-step]")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /agentProcessDone/ }));
  expect(container.querySelector("[data-receipt-step='j1']")).toBeTruthy();
});
