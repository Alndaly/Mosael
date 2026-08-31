/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Job } from "@/api/client";

const h = vi.hoisted(() => ({
  error:
    "ARK request failed: https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks; " +
    '{"code":"InputImageSensitiveContentDetected.PrivacyInformation","request_id":"021788160646919b9f489096afc36acf450c00ec3935d23a968bb2"}',
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/api/client", () => ({
  getJob: async () => null,
  listJobChildren: async () => [],
  listJobEvents: async () => [],
}));

import { JobDetailDialog } from "./JobDetailDialog";

const job = {
  id: "job-1",
  workspace_id: "workspace-1",
  kind: "ai_generation",
  status: "failed",
  progress: 0,
  message: "生成失败",
  error: h.error,
  payload: {},
  result: null,
  created_at: "2026-08-31T14:00:00Z",
  updated_at: "2026-08-31T14:00:01Z",
} as unknown as Job;

describe("任务执行详情宽度", () => {
  it("长 URL 和无空格 JSON 在弹窗内任意断行，不产生横向溢出", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobDetailDialog job={job} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    const error = screen.getByText(h.error);
    expect(error.className).toContain("[overflow-wrap:anywhere]");
    expect(error.className).toContain("whitespace-pre-wrap");

    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("w-[calc(100vw-2rem)]");
    expect(dialog.className).toContain("min-w-0");
    expect(error.parentElement?.className).toContain("min-w-0");
  });
});
