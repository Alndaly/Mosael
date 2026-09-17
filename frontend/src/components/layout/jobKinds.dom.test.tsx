/** @vitest-environment jsdom */
/**
 * 任务种类的界面信息全来自后端目录(ADR-0018);这里只验前端补的那一层:兜底、提示策略、跳转。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

const entry = (kind: string, label: string, announce: string, affects: string[], view: string | null = null, record_field: string | null = null) =>
  ({ kind, label, announce, affects, view, record_field });

vi.mock("@/api/client", () => ({
  fetchJobKinds: async () => ({
    kinds: [
      entry("workflow", "工作流", "always", ["workflows"], "workflows", "workflow_id"),
      entry("proxy", "预览代理", "failures", ["assets"], "no-such-page"),
    ],
    fallback: entry("", "任务", "always", ["assets"]),
  }),
}));

import { jobPage, queryKeysAffectedBy, shouldAnnounce, useJobKinds } from "./jobKinds";

async function kinds() {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const { result } = renderHook(() => useJobKinds(), { wrapper });
  await waitFor(() => expect(result.current.ready).toBe(true));
  return result.current.kindOf;
}

const job = (kind: string, payload: Record<string, unknown> = {}) => ({ id: "j", kind, payload }) as never;

describe("任务种类", () => {
  it("认不出的种类按兜底那一条显示,不把裸 kind 摆到界面上", async () => {
    const kindOf = await kinds();
    const meta = kindOf("some_new_kind");
    expect(meta.label).toBe("任务");
    expect(meta.kind).toBe("some_new_kind");
    expect(meta.icon).toBeTruthy();
  });

  it("提示策略:failures 只在失败时说", async () => {
    const kindOf = await kinds();
    expect(shouldAnnounce(kindOf("proxy"), "succeeded")).toBe(false);
    expect(shouldAnnounce(kindOf("proxy"), "failed")).toBe(true);
    expect(shouldAnnounce(kindOf("workflow"), "succeeded")).toBe(true);
  });

  it("资源换成缓存键", async () => {
    const kindOf = await kinds();
    expect(queryKeysAffectedBy(kindOf("workflow"))).toEqual(["workflows", "workflow-runs"]);
  });

  it("跳转只去前端确实有的页面,带上项目", async () => {
    const kindOf = await kinds();
    expect(jobPage(job("workflow", { project_id: "p1" }), kindOf("workflow"))).toBe("/workflows?p=p1");
    expect(jobPage(job("proxy"), kindOf("proxy"))).toBeNull();
    expect(jobPage(job("mystery"), kindOf("mystery"))).toBeNull();
  });
});
