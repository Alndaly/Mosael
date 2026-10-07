/** @vitest-environment jsdom */

/**
 * 免提浮标对着**眼下这一处的当前对话**说话(ADR 0044 拍板 7)。
 *
 * 在有助手面板的页面(面板收着也算)是那一页的当前对话;别处(素材、发布、设置……)是 AI Studio 的当前对话。那一处还是
 * 草稿就在那一处建一段 —— 和面板发第一句话一样,建出来的就是面板接下来显示的那段。每句带着在哪说的。
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
  isNotFound: () => false,
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
import { resetActivePlaces, useAgentPlace } from "./activePlace";
import { useCurrentAgentSession } from "./currentAgentSession";
import type { AgentPlace } from "./places";
import { adoptAgentSession, readChoice } from "./sessionSelection";

const NOTE: AgentPlace = { kind: "note", id: "n1" };
const STUDIO: AgentPlace = { kind: "studio", id: "" };
const session = (id: string, place: AgentPlace, isMine = true) =>
  ({ id, workspace_id: "w1", title: id, status: "idle", is_mine: isMine, home_kind: place.kind, home_id: place.id, home_name: "", home_state: "ok" }) as never;
const sessions: Record<string, unknown> = {};

/** 一个有助手面板的页面:登记它在哪,面板收着(只读它的当前对话,看面板会显示哪段)。 */
function NotePage({ onPanel }: { onPanel: (id: string | undefined) => void }) {
  const place = useAgentPlace(NOTE);
  onPanel(useCurrentAgentSession("w1", place).session?.id);
  return null;
}

beforeEach(() => {
  window.sessionStorage.clear();
  resetActivePlaces();
  for (const key of Object.keys(sessions)) delete sessions[key];
  sessions["s-note"] = session("s-note", NOTE);
  sessions["s-studio"] = session("s-studio", STUDIO);
  for (const fn of [mocks.listAgentSessions, mocks.createAgentSession, mocks.getAgentSession, mocks.listAgentMessages, mocks.sendAgentMessage]) {
    fn.mockReset();
  }
  mocks.listAgentSessions.mockResolvedValue([]);
  mocks.getAgentSession.mockImplementation(async (id: string) => sessions[id]);
  mocks.listAgentMessages.mockResolvedValue([]);
  mocks.sendAgentMessage.mockResolvedValue({});
  mocks.onUtterance = null;
});

function mount(page: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      {page}
      <VoiceDock workspaceId="w1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

it("在有面板的页面(面板收着):说话进那一页的当前对话,带着在哪说的;AI Studio 那段不碰", async () => {
  adoptAgentSession("w1", NOTE, "s-note");
  adoptAgentSession("w1", STUDIO, "s-studio");
  let panel: string | undefined;
  mount(<NotePage onPanel={(id) => (panel = id)} />);
  await waitFor(() => expect(panel).toBe("s-note"));

  await act(() => mocks.onUtterance!("把这段改短"));
  expect(mocks.sendAgentMessage).toHaveBeenCalledWith("s-note", { content: "把这段改短", place: NOTE });
  expect(mocks.createAgentSession).not.toHaveBeenCalled();
});

it("在没有面板的页面(素材页):说话进 AI Studio 的当前对话", async () => {
  adoptAgentSession("w1", NOTE, "s-note");
  adoptAgentSession("w1", STUDIO, "s-studio");
  mount(null);
  await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith("s-studio"));

  await act(() => mocks.onUtterance!("去发布页"));
  expect(mocks.sendAgentMessage).toHaveBeenCalledWith("s-studio", { content: "去发布页", place: STUDIO });
});

it("那一处还是草稿:在那一处建一段(家在那里),面板当场显示它", async () => {
  mocks.createAgentSession.mockImplementation(async () => {
    sessions["s-voice"] = session("s-voice", NOTE);
    return sessions["s-voice"];
  });
  let panel: string | undefined = "unset";
  mount(<NotePage onPanel={(id) => (panel = id)} />);
  await waitFor(() => expect(panel).toBeUndefined());

  await act(() => mocks.onUtterance!("你好"));
  expect(mocks.createAgentSession).toHaveBeenCalledOnce();
  expect(mocks.createAgentSession).toHaveBeenCalledWith({ workspace_id: "w1", home: NOTE });
  expect(mocks.sendAgentMessage).toHaveBeenCalledWith("s-voice", { content: "你好", place: NOTE });
  await waitFor(() => expect(panel).toBe("s-voice"));
  expect(readChoice("w1", STUDIO)).toBe("");
});

it("那一处是同事共享来只能看的那段:说清楚,不另建一段", async () => {
  sessions["s-shared"] = session("s-shared", NOTE, false);
  adoptAgentSession("w1", NOTE, "s-shared");
  let panel: string | undefined;
  mount(<NotePage onPanel={(id) => (panel = id)} />);
  await waitFor(() => expect(panel).toBe("s-shared"));

  await act(() => mocks.onUtterance!("你好"));
  expect(mocks.createAgentSession).not.toHaveBeenCalled();
  expect(mocks.sendAgentMessage).not.toHaveBeenCalled();
});
