/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  clearReplay: vi.fn(async () => undefined),
  replayUrl: vi.fn((session: string, id: string, which: string) => `/replay/${session}/${id}/${which}`),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string, params?: Record<string, string | number>) =>
    params ? `${key}:${Object.values(params).join(",")}` : key,
}));
vi.mock("@/api/domains/sessions", () => ({
  agentReplayImageUrl: mocks.replayUrl,
  clearAgentReplay: mocks.clearReplay,
}));

import { ToolCalls } from "@/features/agent/ToolCalls";

it("桌面动作的展开明细画出前后证据,并能清空本会话回放", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <ToolCalls tools={[{
        id: "t1",
        name: "computer_desktop_click",
        status: "done",
        args: { token: "snap:0" },
        result: {
          replay: {
            session_id: "s1",
            replay_id: "r1",
            at: "2026-10-25T10:00:00Z",
            action: { kind: "type", text: "hello" },
            before: { url: "/before.png", width: 100, height: 80 },
            after: { url: "/after.png", width: 100, height: 80 },
          },
        },
      }]} />
    </QueryClientProvider>,
  );

  const row = container.querySelector<HTMLElement>("[data-tool-call]")!;
  fireEvent.click(row.querySelector("button[aria-expanded]")!);
  await waitFor(() => expect(container.querySelector("[data-computer-replay]")).toBeTruthy());
  expect(mocks.replayUrl).toHaveBeenCalledWith("s1", "r1", "before");
  expect(mocks.replayUrl).toHaveBeenCalledWith("s1", "r1", "after");
  expect(screen.getByText(/computerReplayType:hello/)).toBeTruthy();
  expect(container.querySelectorAll("[data-computer-replay] img")).toHaveLength(2);

  fireEvent.click(screen.getByRole("button", { name: "computerReplayClear" }));
  await waitFor(() => expect(mocks.clearReplay).toHaveBeenCalledWith("s1"));
});
