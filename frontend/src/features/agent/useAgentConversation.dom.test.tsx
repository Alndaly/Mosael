/** @vitest-environment jsdom */
/**
 * useAgentConversation 不经任何界面直接测(假的 API 层):AI 工作台和助手面板共用的那一份对话运行逻辑。
 * 此前这些只能靠两套组件的 DOM 测试各测一遍。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

const zh = (key: MessageKey) => messages["zh-CN"][key];

vi.mock("@/app/preferences", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useI18n: () => zh,
}));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), message: vi.fn(), success: vi.fn() }) }));
const attachStream = vi.fn(async () => undefined);
vi.mock("@/features/agent/useAgentTurnStream", () => ({
  useAgentTurnStream: () => ({ streamText: "", streamTimeline: [], turnStartedAt: null, attach: attachStream }),
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getAgentSession: vi.fn(async (id: string) => ({ id, status: "idle", context: null })),
  listAgentMessages: vi.fn(async () => []),
  listAgentQueue: vi.fn(async () => [{ id: "q1" }]),
  listAgentUsageEvents: vi.fn(async () => [
    { agent_message_id: "m1", cost: 1 },
    { agent_message_id: "m1", cost: 2 },
    { agent_message_id: null, cost: 3 },
  ]),
  sendAgentMessage: vi.fn(async () => ({ id: "m9" })),
  steerQueuedMessage: vi.fn(async () => ({ steered: false })),
  resumeQueuedMessage: vi.fn(async () => ({})),
  dropQueuedMessage: vi.fn(async () => ({})),
  stopAgentSession: vi.fn(async () => ({})),
  compactAgentSession: vi.fn(async () => ({ compaction: null })),
}));

import { toast } from "sonner";
import { getAgentSession, listAgentQueue, sendAgentMessage, steerQueuedMessage } from "@/api/client";
import type { CurrentAgentSession } from "./currentAgentSession";
import { STUDIO_PLACE } from "./places";
import { useAgentConversation } from "./useAgentConversation";

function fakeCurrent(sessionId: string | null): CurrentAgentSession {
  return {
    place: STUDIO_PLACE,
    session: sessionId ? ({ id: sessionId } as never) : null,
    ensure: vi.fn(async () => ({ id: sessionId ?? "created" }) as never),
  } as unknown as CurrentAgentSession;
}

function render(current: CurrentAgentSession) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { ...renderHook(() => useAgentConversation(current, "w1"), { wrapper }), invalidate };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("useAgentConversation", () => {
  it("草稿时一个请求都不发;发第一条才在这一处建会话,发完记下开跑、刷新清单、接上流", async () => {
    const current = fakeCurrent(null);
    const { result, invalidate } = render(current);
    expect(getAgentSession).not.toHaveBeenCalled();
    expect(listAgentQueue).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.send.mutateAsync({
        content: "hi",
        references: [],
        document: { type: "doc", content: [] },
        context: "页面上下文",
      });
    });
    expect(current.ensure).toHaveBeenCalledTimes(1);
    expect(sendAgentMessage).toHaveBeenCalledWith("created", {
      content: "hi",
      references: [],
      context: "页面上下文",
      body_document: { type: "doc", content: [] },
      place: { kind: STUDIO_PLACE.kind, id: STUDIO_PLACE.id },
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agent-sessions", "w1"] });
    expect(attachStream).toHaveBeenCalledWith("created");
  });

  it("有会话时读详情、排队、用量;用量按回复归好", async () => {
    const { result } = render(fakeCurrent("s1"));
    await waitFor(() => expect(result.current.queuedIds.has("q1")).toBe(true));
    await waitFor(() => expect(result.current.usageByMessage.get("m1")).toHaveLength(2));
    expect(result.current.usageByMessage.size).toBe(1);
    expect(result.current.running).toBe(false);
  });

  it("插话晚了(这一轮先结束)要说出来,并刷新排队与消息", async () => {
    const { result, invalidate } = render(fakeCurrent("s1"));
    await act(async () => {
      await result.current.steerQueued.mutateAsync("q1");
    });
    expect(steerQueuedMessage).toHaveBeenCalledWith("s1", "q1");
    expect(toast.message).toHaveBeenCalledWith(zh("chatSteerTooLate"));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agent-queue", "s1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agent-messages", "s1"] });
  });

  it("继续发送之后会话状态也要重读(它可能当场开跑);没得整理要说出来", async () => {
    const { result, invalidate } = render(fakeCurrent("s1"));
    await act(async () => {
      await result.current.resumeQueued.mutateAsync("q1");
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["agent-session", "s1"] });
    await act(async () => {
      await result.current.compact.mutateAsync();
    });
    expect(toast.message).toHaveBeenCalledWith(zh("agentCompactNothing"));
  });
});
