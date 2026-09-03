/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

/**
 * 检查器里那一栏「输出变量」列的是**名字**(`{{llm-1.text}}`)。名字回答"我怎么引用它",
 * 而调工作流时真正要问的是"它这次给了什么" —— 两个问题,此前只答了第一个。
 */

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", () => ({ api: vi.fn(), assetFileUrl: (id: string) => `/f/${id}` }));
vi.mock("@/components/app/asset-preview", () => ({
  AssetInlinePreview: ({ assetId }: { assetId: string }) => <img data-testid="asset" alt="" src={`/t/${assetId}`} />,
}));

import { RunOutputs } from "@/features/workflows/RunOutputs";
import type { RegistryLike } from "@/features/workflows/analyze";
import type { Step } from "@/features/workflows/runSteps";

const registry: RegistryLike = {
  get(nodeType) {
    const table: Record<string, { output_types: Record<string, string> }> = {
      ai_generate: { output_types: { asset_id: "asset", generation_id: "text" } },
      llm: { output_types: { text: "text" } },
    };
    return table[nodeType];
  },
};

function mount(step: Step, nodeType = "llm") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <RunOutputs registry={registry} nodeType={nodeType} step={step} />
    </QueryClientProvider>,
  );
}

const base: Step = { nid: "n1", name: "LLM", status: "done", ms: 1234 };

describe("这一步给了什么", () => {
  it("值和键名都摆出来", () => {
    mount({ ...base, outputs: { text: "模型回的那段话" } });
    expect(screen.getByText("text")).toBeTruthy();
    expect(screen.getByText("模型回的那段话")).toBeTruthy();
  });

  it("耗时按秒显示,毫秒级才用 ms", () => {
    mount({ ...base, ms: 1234, outputs: { text: "x" } });
    expect(screen.getByText(/1\.2s/)).toBeTruthy();
  });

  it("失败时把错误原文摆出来,而不是只标一个红点", () => {
    // 只标状态的话,用户得去翻执行历史才知道为什么 —— 而那正是他此刻在看的这个节点。
    mount({ ...base, status: "failed", error: "上游返回 429", outputs: undefined });
    expect(screen.getByText("上游返回 429")).toBeTruthy();
  });

  it("没有产出时说一句,而不是留一片空白", () => {
    mount({ ...base, outputs: {} });
    expect(screen.getByText("wfRunNoOutputs")).toBeTruthy();
  });

  it("长文本折起来,但开头仍然看得见", () => {
    // 只给个"展开"按钮的话,用户得点开才知道值不值得点开。
    const long = "很长".repeat(300);
    const { container } = mount({ ...base, outputs: { text: long } });
    expect(container.querySelector("details")).toBeTruthy();
    expect(container.textContent).toContain("很长很长");
  });

  it("短文本不折 —— 为了一行字点一下是多余的", () => {
    const { container } = mount({ ...base, outputs: { text: "短" } });
    expect(container.querySelector("details")).toBeNull();
  });

  it("素材走缩略图,不把裸 id 打在屏幕上", () => {
    const { container } = mount({ ...base, outputs: { asset_id: "abc123" } }, "ai_generate");
    expect(container.textContent).not.toContain("abc123");
  });
});
