/** @vitest-environment jsdom */

/**
 * 空闲时对话跟着会话本身动:状态或 `updated_at` 一变,消息和排队的那几条一起重取。
 *
 * 排队条空闲时也要读(D63:按了停止,排着的话被扣下,等人点「继续发送」),但不轮询 —— 它和消息一样只会因为一轮而变
 * (轮到了、被停止扣下)。一轮收尾时状态从 running 变回 idle:这一下没重取队列的话,条上还是停之前的那份(没带 held,
 * 给的是插不进去的「插话」),或者干脆是空的。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { useTranscriptFollowsSession } from "./transcriptFollowsSession";

function Follower({ session }: { session: { status: string; updated_at: string } }) {
  useTranscriptFollowsSession("s1", session);
  return null;
}

it("一轮收尾(running → idle):消息和排队的那几条一起重取;刚挂上时不多取一次", () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={client}>
      <Follower session={{ status: "running", updated_at: "2026-10-09T00:00:00" }} />
    </QueryClientProvider>,
  );
  expect(invalidate).not.toHaveBeenCalled();

  view.rerender(
    <QueryClientProvider client={client}>
      <Follower session={{ status: "idle", updated_at: "2026-10-09T00:00:05" }} />
    </QueryClientProvider>,
  );
  const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
  expect(keys).toContain(JSON.stringify(["agent-messages", "s1"]));
  expect(keys).toContain(JSON.stringify(["agent-queue", "s1"]));
});
