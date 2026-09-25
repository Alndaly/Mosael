/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 自动放行留了痕,而**人此前看不到**。
 *
 * 前端对 `/api/confirmations` 的两个调用点都写死 `status=pending`,于是 `decision_mode` 和
 * `resolved_at` 这半边在界面上根本不存在:用户开了 auto 档之后,智能体每做一次本该问他的
 * 写操作,他看到的只是"它做了这件事",看不到"这件事本来要问你"。
 *
 * 这几条钉的是那一跳:请求真的带 `status=approved`,手动批的不混进来,一条都没有时整块不出现。
 */

const listed = vi.fn();
vi.mock("@/api/client", () => ({ api: (path: string) => listed(path) }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const { AutoApprovalTrace } = await import("./AutoApprovalTrace");

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AutoApprovalTrace workspaceId="ws" sessionId="s1" />
    </QueryClientProvider>,
  );
}

const card = (id: string, decision_mode: string, summary: string) => ({
  id,
  tool: "publish_video",
  summary,
  decision_mode,
  resolved_at: "2026-09-23T01:00:00Z",
});

beforeEach(() => listed.mockReset());

it("问的是这次会话里**已批准**的卡,而不是待办的", async () => {
  listed.mockResolvedValue([]);

  show();

  await waitFor(() => expect(listed).toHaveBeenCalled());
  const path = listed.mock.calls[0][0] as string;
  expect(path).toContain("status=approved");
  expect(path).toContain("session_id=s1");
  expect(path).not.toContain("status=pending");
});

it("列出被哪一档放行的,而不是笼统一句「已批准」", async () => {
  listed.mockResolvedValue([card("a", "auto", "发布到 B 站"), card("b", "bypass", "跑一段代码")]);

  show();

  expect(await screen.findByText("发布到 B 站")).toBeInTheDocument();
  expect(screen.getByText(/permTraceGateAuto/)).toBeInTheDocument();
  expect(screen.getByText(/permTraceGateBypass/)).toBeInTheDocument();
});

it("手动批的不混进来 —— 那是他自己一张一张点过的,他知道", async () => {
  listed.mockResolvedValue([card("a", "manual", "他自己点的那次"), card("b", "auto", "替他答的那次")]);

  expect(await (async () => {
    show();
    await screen.findByText("替他答的那次");
    return screen.queryByText("他自己点的那次");
  })()).toBeNull();
});

it("一次都没自动放行过时整块不出现 —— 常驻一句「暂无」只是噪音", async () => {
  listed.mockResolvedValue([card("a", "manual", "他自己点的")]);

  show();

  await waitFor(() => expect(listed).toHaveBeenCalled());
  expect(screen.queryByText(/permTraceTitle/)).not.toBeInTheDocument();
});

it("摘要里的 **强调** 渲染成粗体,悬停提示是纯文本", async () => {
  // 确认卡摘要来自后端文案目录:「⚠️ **不隔离**,直接在你的电脑上运行一段 Python」。
  listed.mockResolvedValue([card("a", "bypass", "⚠️ **不隔离**,直接运行")]);

  show();

  const strong = await screen.findByText("不隔离");
  expect(strong.tagName).toBe("STRONG");
  expect(strong.closest("[title]")?.getAttribute("title")).toBe("⚠️ 不隔离,直接运行");
});
