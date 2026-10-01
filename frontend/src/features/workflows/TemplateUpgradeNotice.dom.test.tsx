/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 从旧版官方模板建出来的图:编辑器顶上说一声,点一下按新版重建一张(旧图原样保留)。1.8.0 时建的那几张里有注定
 * 失败的,而图不迁移(它是用户的数据)—— 不提示的话,用户只会在付完钱之后看到失败。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TemplateUpgradeNotice } from "@/features/workflows/TemplateUpgradeNotice";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  cleanup();
});

const posted: string[] = [];

function renderNotice(meta: Record<string, unknown> | undefined) {
  posted.length = 0;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    if (init?.method === "POST") {
      posted.push(url.pathname);
      return new Response(JSON.stringify({ id: "w-new", workspace_id: "ws", name: "混剪(新版模板)" }), {
        status: 200, headers: { "content-type": "application/json" },
      });
    }
    const body = url.pathname.endsWith("/workflows/templates")
      ? [{ id: "footage_montage", name: "自有素材混剪", description: "", version: 3, stages: [], requirements: [] }]
      : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TemplateUpgradeNotice workflowId="w-old" meta={meta as never} />
    </QueryClientProvider>,
  );
}

describe("旧版模板建的图", () => {
  it("版本低于现行模板:说一声,点一下按新版重建", async () => {
    renderNotice({ template_id: "footage_montage", template_version: 2, source: "official" });
    expect(await screen.findByText("wfTemplateOutdated")).toBeInTheDocument();
    fireEvent.click(screen.getByText("wfTemplateRebuild"));
    await waitFor(() => expect(posted).toEqual(["/api/workflows/w-old/rebuild-from-template"]));
  });

  it("已经是现行版本,或者不是从官方模板建的:什么都不说", async () => {
    renderNotice({ template_id: "footage_montage", template_version: 3, source: "official" });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText("wfTemplateOutdated")).toBeNull();
    cleanup();
    renderNotice(undefined);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText("wfTemplateOutdated")).toBeNull();
  });
});
