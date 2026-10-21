/** @vitest-environment jsdom */
/**
 * 一轮回答分成「过程」和「结果」:过程收成一行摘要,结果一直摊着。
 *
 * 每一条对应一个具体的坏结果:
 * - 跑完了过程还摊着 → 答案被挤在一屏工具行下面(用户要往下翻才找得到它说了什么);
 * - 跑着的时候就收起 → 看不见它在干什么,以为卡住了;
 * - 失败、没结果、有卡等人拍板时收起 → 断在哪一步、要点的那张卡都被藏进一行摘要里;
 * - 生成的图挂在工具行明细里 → 收起过程,图也跟着没了。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: async (path: string) => {
    const id = path.split("/").pop() ?? "";
    return { id, name: `素材 ${id}`, kind: "image", workspace_id: "w" };
  },
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("streamdown", () => ({
  Streamdown: ({ children }: { children: string }) => <div>{children}</div>,
  CodeBlockCopyButton: () => <button type="button" />,
}));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: () => {} }) }));
//: 卡本身长什么样不归这里管(InlineConfirmations 有自己的测试):只看它挂没挂在那一行下面。
vi.mock("@/features/agent/InlineConfirmations", () => ({ PendingConfirmationCard: () => <div data-pending-card="" /> }));
const opened = vi.hoisted(() => [] as string[]);
vi.mock("@/lib/deepLink", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  gotoAsset: (id: string) => opened.push(id),
}));

import type { Confirmation } from "@/api/client";
import { DecisionsContext, type Decisions } from "@/features/agent/decisionsContext";
import { AgentTurnContent, splitTurn, turnBlocks, type AgentTimelineItem } from "@/features/agent/ToolCalls";
import { formatElapsedSeconds } from "@/lib/time";

afterEach(() => {
  cleanup();
  opened.length = 0;
});

const work: AgentTimelineItem[] = [
  { type: "thinking", text: "想一想", done: true, duration_seconds: 2 },
  { type: "text", text: "我先查一下素材" },
  { type: "tool", tool: { id: "t1", name: "list_assets", status: "done", args: { query: "猫" }, result: [] } },
  { type: "tool", tool: { id: "t2", name: "get_job", status: "done", args: { job_id: "j" }, result: { status: "succeeded", result: { asset_ids: ["img-1", "img-2"] } } } },
  { type: "text", text: "图片已生成" },
];

function renderTurn(props: Partial<React.ComponentProps<typeof AgentTurnContent>>, decisions?: Decisions) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const turn = <AgentTurnContent timeline={work} {...props} />;
  return render(
    <QueryClientProvider client={client}>
      {decisions ? <DecisionsContext.Provider value={decisions}>{turn}</DecisionsContext.Provider> : turn}
    </QueryClientProvider>,
  );
}

const processRow = () => document.querySelector("[data-tool-call='t1']");

describe("过程和结果的分界", () => {
  it("末尾连着的正文是结果,中途的旁白算过程", () => {
    const { process, result } = splitTurn(turnBlocks(work));
    expect(result).toEqual([{ type: "text", text: "图片已生成" }]);
    expect(process.map((block) => block.type)).toEqual(["thinking", "text", "tools"]);
  });
});

describe("一轮回答", () => {
  it("跑完了:过程收成一行摘要(几步、多久),答案和做出来的图摊在下面", async () => {
    renderTurn({ durationSeconds: 32 });
    const summary = screen.getByRole("button", { name: `agentProcessDone · ${formatElapsedSeconds(32)}` });
    expect(summary.getAttribute("aria-expanded")).toBe("false");
    // 「{n}」由调用处替换;这里 t 原样回 key,所以只看到 key —— 步数另外核:思考 1 + 工具 2。
    expect(processRow()).toBeNull();
    expect(screen.getByText("图片已生成")).toBeTruthy();
    const result = document.querySelector("[data-turn-result]");
    await waitFor(() => expect(result?.querySelectorAll("img")).toHaveLength(2));
    fireEvent.click(summary);
    expect(processRow()).not.toBeNull();
  });

  it("结果区的图可以去素材库;工具行自己不再为素材摊开", async () => {
    renderTurn({});
    const reveal = await screen.findAllByRole("button", { name: "agentOutputOpenInLibrary" });
    fireEvent.click(reveal[1]);
    expect(opened).toEqual(["img-2"]);
    fireEvent.click(screen.getByRole("button", { name: /agentProcessDone/ }));
    expect(document.querySelector("[data-tool-call='t2'] [data-tool-details]")).toBeNull();
  });

  it("还在跑:过程摊着,摘要说「处理中」", () => {
    renderTurn({ running: true });
    expect(screen.getByRole("button", { name: "agentProcessRunning" }).getAttribute("aria-expanded")).toBe("true");
    expect(processRow()).not.toBeNull();
  });

  it("失败了、没有结果:过程不收", () => {
    const failed = renderTurn({ failed: true });
    expect(processRow()).not.toBeNull();
    failed.unmount();
    renderTurn({ timeline: work.slice(0, 3) });
    expect(processRow()).not.toBeNull();
  });

  it("有卡在等人拍板:过程不收,卡挂在发起它的那一行下面", () => {
    const pending = { id: "c1", tool_call_id: "t1", status: "pending" } as unknown as Confirmation;
    renderTurn(
      { durationSeconds: 5 },
      { sessionId: "s", readOnly: true, byToolCall: new Map([["t1", pending]]), pending: [pending], actionsFor: () => null },
    );
    expect(processRow()?.querySelector("[data-pending-card]")).not.toBeNull();
  });

  it("做出来的图是答案文档的一部分:跑着就在,位置在产出它的步骤之后(时间线顺序)", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const tree = (running: boolean) => (
      <QueryClientProvider client={client}>
        <AgentTurnContent timeline={work} running={running} />
      </QueryClientProvider>
    );
    const view = render(tree(true));
    // 跑着:工具一交图,文档流里立刻有它 —— 图在产出它的步骤之后、总结正文之前。
    const result = document.querySelector("[data-turn-result]");
    await waitFor(() => expect(result?.querySelectorAll("img")).toHaveLength(2));
    const children = [...(result?.children ?? [])];
    const imgIndex = children.findIndex((child) => child.querySelector("img"));
    const textIndex = children.findIndex((child) => child.textContent === "图片已生成");
    expect(imgIndex, "图在正文前面(时间线:先产出、后总结)").toBeGreaterThanOrEqual(0);
    expect(imgIndex).toBeLessThan(textIndex);
    view.rerender(tree(false));
    await waitFor(() => expect(document.querySelector("[data-turn-result]")?.querySelectorAll("img")).toHaveLength(2));
  });

  it("过程只有一段思考:不套摘要,思考块自己收起", () => {
    renderTurn({ timeline: [{ type: "thinking", text: "想", done: true }, { type: "text", text: "好的" }] });
    expect(screen.queryByRole("button", { name: /agentProcess/ })).toBeNull();
    expect(screen.getByText("agentThought")).toBeTruthy();
  });

  it("回执带来的图接在这一轮自己的产出后面,同一张不摆两遍", async () => {
    renderTurn({ receivedAssetIds: ["img-2", "img-3"] });
    const result = document.querySelector("[data-turn-result]");
    await waitFor(() => expect(result?.querySelectorAll("img")).toHaveLength(3));
  });
});
