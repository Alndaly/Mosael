/** @vitest-environment jsdom */

/**
 * 一次选择的结果**属于用户做了什么**,不属于助手说话。
 *
 * 维护者截图:助手那条消息里的选择卡上写着「你在选择卡上选了 …」—— 用户点的东西被画进助手
 * 那一侧,由助手用第一人称转述。原话:「为何当前还是会显示选择结果到我的消息卡 这是不对的」。
 *
 * 记录该在**用户那条消息**里:后端 `deliver_to_session` 送回来的那条,`payload.answers` 带着
 * 「问的是什么、选的是哪一项」(见 backend/app/domain/agent/questions.py 的说明),界面据此
 * 把结构画回来。助手那一侧只留一行**状态**(这一步的调用拿回了答案),不是一句转述、也不是
 * 一张把同一件事再记一遍的卡。
 *
 * 这里用**真的中文文案**:要钉住的正是那句话长什么样。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return {
    useI18n: () => (key: string) => (messages["zh-CN"] as Record<string, string>)[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});
vi.mock("@/features/agent/messageUsage", () => ({
  MessageFooter: ({ children }: { children?: React.ReactNode }) => <div data-testid="footer">{children}</div>,
  MessageTime: () => null,
  MessageUsageFooter: () => null,
}));

import { ChatBubble } from "./ChatBubble";
import { ToolResultCard } from "./toolResultShapes";

const picked = {
  question_id: "q1",
  picked: [{ question: "接下来怎么走？", choices: ["先暂停"] }],
};

const agentMessage = (role: string, payload: unknown, content = "") =>
  ({
    id: `${role}-1`,
    role,
    content,
    payload,
    error: null,
    created_at: "2026-10-20T00:00:00Z",
  }) as unknown as Parameters<typeof ChatBubble>[0]["message"];

function renderInClient(node: React.ReactElement) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {node}
    </QueryClientProvider>,
  );
}

describe("助手那一侧:只写这一步拿到了什么,不转述用户的话", () => {
  it("选择结果不是一句「你在选择卡上选了 …」", () => {
    const { container } = render(
      <ToolResultCard
        value={{ status: "answered", answers: { "接下来怎么走？": ["先暂停"] } }}
      />,
    );
    // 用户截图里那一行:第一人称,由助手替用户说的。
    expect(container.textContent ?? "").not.toMatch(/你选了|你在选择卡上选了|你跳过/);
    // 状态式:名词性标签 + 值,不是一句话。
    expect(container.textContent).toContain("已选");
    expect(container.textContent).toContain("先暂停");
  });

  it("跳过也只是一个状态,不是一句「你跳过了…」", () => {
    const { container } = render(<ToolResultCard value={{ status: "dismissed", skipped: true }} />);
    expect(container.textContent ?? "").not.toMatch(/你跳过|你选择了/);
    expect(container.textContent).toContain("已跳过");
  });
});

describe("用户那一侧:选择记在用户自己的那条消息里", () => {
  it("消息里画着问的是什么、选的是哪一项", () => {
    const { container } = renderInClient(
      <ChatBubble message={agentMessage("user", { answers: picked })} usageEvents={[]} workspaceId="w1" />,
    );
    const record = container.querySelector("[data-answer-record]");
    expect(record, "选择记录该在用户那条消息里画出来").toBeTruthy();
    expect(record!.textContent).toContain("接下来怎么走？");
    expect(record!.textContent).toContain("先暂停");
    expect(record!.textContent).toContain("已选");
    // 发给模型的正文(「我选好了:」)不该出现在界面上。
    expect(container.textContent ?? "").not.toContain("我选好了");
  });

  it("跳过:也只是用户那条消息里的一个状态", () => {
    const { container } = renderInClient(
      <ChatBubble
        message={agentMessage("user", { answers: { dismissed: true, question_id: "q1" } })}
        usageEvents={[]}
        workspaceId="w1"
      />,
    );
    expect(container.querySelector("[data-answer-record]")).toBeTruthy();
    expect(container.textContent).toContain("已跳过");
    expect(container.textContent ?? "").not.toMatch(/你跳过了/);
  });
});
