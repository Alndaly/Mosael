/** @vitest-environment jsdom */
/**
 * 用户气泡的宽度只由它自己的字决定。
 *
 * 气泡和一行悬停才显形的脚注(相对时间 + 复制)排在同一列里。脚注透明但占宽度,而相对时间每 30 秒
 * 重算(「刚刚」→「3 分钟前」):此前那一列是 items-stretch,气泡被拉到脚注那么宽,于是短消息右边多
 * 一截空白,还时不时伸缩。jsdom 不排版,这里钉的是对齐方式:气泡不被拉伸,靠右。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/features/agent/messageUsage", () => ({
  MessageFooter: ({ children, className }: { children: React.ReactNode; className?: string }) => (
    <div data-testid="footer" className={className}>{children}</div>
  ),
  MessageTime: ({ iso }: { iso: string }) => <span>{iso}</span>,
  MessageUsageFooter: () => null,
}));

import { ChatBubble } from "./ChatBubble";

it("用户气泡不被悬停脚注撑宽:那一列靠右对齐,不拉伸", () => {
  const message = {
    id: "m1",
    role: "user",
    content: "你是",
    payload: null,
    created_at: "2026-09-26T08:00:00Z",
  } as unknown as Parameters<typeof ChatBubble>[0]["message"];
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ChatBubble message={message} usageEvents={[]} workspaceId="w1" />
    </QueryClientProvider>,
  );
  const column = screen.getByTestId("footer").parentElement as HTMLElement;
  expect(column.className).toContain("items-end");
  expect(column.className).not.toContain("items-stretch");
});
