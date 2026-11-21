import { QueryClient } from "@tanstack/react-query";
import { expect, it } from "vitest";

import { markAgentTurnStarted } from "./agentTurnStarts";

it("让进度当帧出现:会话立即变 running,并立刻重取消息与队列", () => {
  const qc = new QueryClient();
  const session = { id: "s1", status: "idle", title: "会话" };
  qc.setQueryData(["agent-session", "s1"], session);
  qc.setQueryData(["agent-messages", "s1"], []);
  qc.setQueryData(["agent-queue", "s1"], []);

  markAgentTurnStarted(qc, "s1");

  expect(qc.getQueryData(["agent-session", "s1"])).toEqual({ ...session, status: "running" });
  for (const key of ["agent-session", "agent-messages", "agent-queue"]) {
    expect(qc.getQueryState([key, "s1"])?.isInvalidated, `${key} 必须重取`).toBe(true);
  }
});
