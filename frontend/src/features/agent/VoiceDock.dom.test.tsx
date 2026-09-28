/** @vitest-environment jsdom */

/**
 * 免提浮标对着**面板正显示的那条**会话说话。
 *
 * 此前面板在没有存储时回落到清单第一条,而浮标只读 localStorage —— 读到空就新建一条,于是
 * 你对着浮标说的话进了一条面板上看不见的新会话。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listAgentSessions: vi.fn(),
  createAgentSession: vi.fn(),
  updateAgentSession: vi.fn(),
  getAgentSession: vi.fn(),
  listAgentMessages: vi.fn(),
  sendAgentMessage: vi.fn(),
  onUtterance: null as null | ((text: string) => Promise<void>),
}));
vi.mock("@/api/client", () => mocks);
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/features/agent/VoiceOrb", () => ({ VoiceOrb: () => null }));
vi.mock("@/components/app/useFloatingPanel", () => ({
  useFloatingPanel: () => ({ style: {}, startDrag: () => {}, wasDragged: () => false, focusProps: {} }),
}));
vi.mock("@/features/agent/useVoiceLoop", () => ({
  useVoiceLoop: (options: { onUtterance: (text: string) => Promise<void> }) => {
    mocks.onUtterance = options.onUtterance;
    return { on: true, state: "listening", heard: "", levelRef: { current: 0 }, start: vi.fn(), stop: vi.fn() };
  },
}));

import { VoiceDock } from "./VoiceDock";
import { useCurrentAgentSession } from "./currentAgentSession";
import { agentSessionSelectionKey } from "./sessionSelection";

const session = (id: string) => ({ id, workspace_id: "w1", title: id }) as never;

/** 面板那一侧:它显示的是哪一条。 */
function PanelProbe({ onSession }: { onSession: (id: string | undefined) => void }) {
  const current = useCurrentAgentSession("w1");
  onSession(current.session?.id);
  return null;
}

beforeEach(() => {
  window.localStorage.clear();
  for (const fn of [
    mocks.listAgentSessions,
    mocks.createAgentSession,
    mocks.getAgentSession,
    mocks.listAgentMessages,
    mocks.sendAgentMessage,
  ]) fn.mockReset();
  mocks.getAgentSession.mockResolvedValue({ status: "idle" });
  mocks.listAgentMessages.mockResolvedValue([]);
  mocks.sendAgentMessage.mockResolvedValue({});
  mocks.onUtterance = null;
});

function mount(onPanel: (id: string | undefined) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PanelProbe onSession={onPanel} />
      <VoiceDock workspaceId="w1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

it("面板回落到第一条、从没选过:对浮标说话进的就是那一条,不新建", async () => {
  mocks.listAgentSessions.mockResolvedValue([session("s-shown"), session("s-older")]);
  let panel: string | undefined;
  mount((id) => (panel = id));
  await waitFor(() => expect(panel).toBe("s-shown"));

  await act(() => mocks.onUtterance!("去发布页"));
  expect(mocks.createAgentSession).not.toHaveBeenCalled();
  expect(mocks.sendAgentMessage).toHaveBeenCalledWith("s-shown", { content: "去发布页" });
  // 说了话就算选过了:之后别的会话更活跃也不会把它顶掉。
  expect(window.localStorage.getItem(agentSessionSelectionKey("w1"))).toBe("s-shown");
});

it("一条都没有时浮标建的会话,已经打开的面板当场切过去", async () => {
  mocks.listAgentSessions.mockResolvedValue([]);
  mocks.createAgentSession.mockResolvedValue(session("s-voice"));
  let panel: string | undefined = "unset";
  mount((id) => (panel = id));
  await waitFor(() => expect(mocks.listAgentSessions).toHaveBeenCalled());
  await waitFor(() => expect(panel).toBeUndefined());

  await act(() => mocks.onUtterance!("你好"));
  expect(mocks.createAgentSession).toHaveBeenCalledOnce();
  expect(mocks.sendAgentMessage).toHaveBeenCalledWith("s-voice", { content: "你好" });
  expect(panel).toBe("s-voice");
});
