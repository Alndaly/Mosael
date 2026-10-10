/** @vitest-environment jsdom */
/**
 * 这一页认得的工具结果(ADR 0042 §5,见 pageViews):工作台的「助手」把诊断画成一条条带「定位」「照这个改」的问题。
 * 结果属于这次工具调用,所以放在它的展开明细里;有可操作结果时自动展开,不再画成工具行之后的另一张卡。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview: vi.fn() }),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AgentPageViewsContext, type AgentPageViews } from "@/features/agent/pageViews";
import { ToolCalls } from "@/features/agent/ToolCalls";

const FINDINGS = { findings: [{ ref: "8", severity: "error", kind: "link_type_mismatch", cause: "「vae」要 VAE,接进来的是 CLIP" }],
                   counts: { error: 1, warning: 0 } };

function rows(views: AgentPageViews | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AgentPageViewsContext.Provider value={views}>
        <ToolCalls tools={[
          { id: "t1", name: "comfy_check", status: "done", args: { instance_id: "i1" }, result: { result: FINDINGS } },
          { id: "t2", name: "comfy_check", status: "error", args: {}, result: "先在工作台里打开这台 ComfyUI" },
        ]} />
      </AgentPageViewsContext.Provider>
    </QueryClientProvider>,
  );
}

it("这一页认得的结果放进工具明细并自动展开;交给它的是拆过包的结构化结果和工具名", () => {
  const seen: [string, unknown][] = [];
  const views: AgentPageViews = {
    toolResult: (tool, data) => {
      seen.push([tool, data]);
      return <div data-page-card="">诊断卡</div>;
    },
  };
  const view = rows(views);
  const [first] = view.container.querySelectorAll("[data-tool-call]");
  expect(first.querySelector("[aria-expanded]")!.getAttribute("aria-expanded"), "有页面结果就自动展开").toBe("true");
  expect(first.querySelector("[data-page-card]")!.textContent).toBe("诊断卡");
  expect(first.querySelector("[data-tool-details] [data-page-card]"), "结果在这次工具调用的明细内").toBeTruthy();
  expect(seen[0]).toEqual(["comfy_check", FINDINGS]);
  expect(view.container.querySelectorAll("[data-page-card]"), "失败的那一次不画").toHaveLength(1);
  fireEvent.click(screen.getAllByRole("button", { expanded: true })[0]);
  expect(first.querySelector("[data-page-card]"), "收起这次调用就一起收起结果").toBeNull();
  fireEvent.click(screen.getAllByRole("button", { expanded: false })[0]);
  expect(view.container.querySelectorAll("[data-page-card]"), "展开也只有这一张,不重复").toHaveLength(1);
});

it("工具失败原因也在这次调用的明细内,默认展开", () => {
  const view = rows(null);
  const failed = view.container.querySelectorAll<HTMLElement>("[data-tool-call]")[1];
  expect(failed.querySelector("[aria-expanded]")?.getAttribute("aria-expanded")).toBe("true");
  expect(failed.querySelector("[data-tool-details] [data-tool-failure]"), "失败回包不是兄弟卡片").toBeTruthy();
});

it("没有这一层(AI 工作台)、或者这一页不认得:只有那一行", () => {
  const plain = rows(null);
  expect(plain.container.querySelector("[data-page-card]")).toBeNull();
  plain.unmount();
  const unknown = rows({ toolResult: () => null });
  expect(unknown.container.querySelectorAll("[data-tool-call]")[0].children).toHaveLength(1);
});
