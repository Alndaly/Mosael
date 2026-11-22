import { QueryClient } from "@tanstack/react-query";
import { expect, it } from "vitest";

import { markAgentTurnStarted } from "./agentTurnStarts";
import { agentKeys } from "@/api/queryKeys";

it("让进度当帧出现:会话立即变 running,并立刻重取消息与队列", () => {
  const qc = new QueryClient();
  const session = { id: "s1", status: "idle", title: "会话" };
  qc.setQueryData(agentKeys.session("s1"), session);
  qc.setQueryData(agentKeys.messages("s1"), []);
  qc.setQueryData(agentKeys.queue("s1"), []);

  markAgentTurnStarted(qc, "s1");

  expect(qc.getQueryData(agentKeys.session("s1"))).toEqual({ ...session, status: "running" });
  for (const key of ["agent-messages", "agent-queue"]) {
    expect(qc.getQueryState([key, "s1"])?.isInvalidated, `${key} 必须重取`).toBe(true);
  }
});
