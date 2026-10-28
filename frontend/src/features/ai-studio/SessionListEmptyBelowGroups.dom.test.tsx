/** @vitest-environment jsdom */

/**
 * 左边那一列有分组时,「这里一条都没有」的空态排在**分组下面**、占剩下的那一截(维护者 2026-10-29:分组跑到了空态底下,
 * 空态贴着搜索框居中,下面一大片空着)。分组包括自己建的,也包括创作页收在最后的「来自别处」。
 *
 * 钉三件事:分组在前、空态在后;建过分组而这一类一条都没有时空态照说(此前整个不出现,只剩一排「某某 0」);
 * 空态那一块是撑满剩余高度的那一段(`flex-1`),不是挤在列表头上。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const TEXT: Record<string, string> = {
  generationNoSessions: "还没有创作会话",
  generationSearchSessions: "搜索创作会话…",
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEXT[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { SessionList, type ListedSession } from "@/features/ai-studio/SessionList";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
});

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const GROUP = { id: "g1", workspace_id: "w1", kind: "generation", name: "片头", created_at: "2026-10-29T00:00:00Z" };

type Row = ListedSession & { origin: string };

function row(id: string, title: string, origin = "studio"): Row {
  return { id, title, group_id: null, is_mine: true, shared: false, origin };
}

function renderList({ sessions, groups }: { sessions: Row[]; groups: unknown[] }) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
    new Response(JSON.stringify(String(input).includes("/api/session-groups") ? groups : []), {
      status: 200,
      headers: { "content-type": "application/json" },
    })) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SessionList<Row>
        kind="generation"
        workspaceId="w1"
        sessions={sessions}
        loading={false}
        loaded
        activeSessionId={null}
        onSelect={() => {}}
        onCreate={() => {}}
        creating={false}
        onDeleted={() => {}}
        aside={{ title: "来自别处", isAside: (session) => session.origin !== "studio" }}
      />
    </QueryClientProvider>,
  );
}

const empty = () => document.querySelector<HTMLElement>("[data-session-empty]");

/** a 在文档里排在 b 前面。 */
const precedes = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("有分组时,空态在分组下面、撑满剩下的高度", () => {
  it("只有「来自别处」:那一组在上,空态在下", async () => {
    renderList({ sessions: [row("s1", "工作流里出的视频", "workflow")], groups: [] });
    const aside = await waitFor(() => {
      const found = document.querySelector("[data-session-aside]");
      expect(found).toBeTruthy();
      return found as HTMLElement;
    });
    expect(screen.getByText(TEXT.generationNoSessions)).toBeTruthy();
    expect(precedes(aside, empty()!), "「来自别处」被挤到空态底下了").toBe(true);
    expect(empty()!.className.split(" ")).toContain("flex-1");
  });

  it("建过分组、这一类一条都没有:分组照样在上,空态照说(不是只剩一排「片头 0」)", async () => {
    renderList({ sessions: [], groups: [GROUP] });
    const toggle = await waitFor(() => {
      const found = document.querySelector("[data-group-toggle]");
      expect(found).toBeTruthy();
      return found as HTMLElement;
    });
    expect(screen.getByText(TEXT.generationNoSessions)).toBeTruthy();
    expect(precedes(toggle, empty()!)).toBe(true);
  });

  it("这里开过的有(哪怕都收在分组里):不说「一条都没有」", async () => {
    renderList({ sessions: [{ ...row("s2", "海报"), group_id: "g1" }], groups: [GROUP] });
    await waitFor(() => expect(document.querySelector("[data-group-toggle]")).toBeTruthy());
    expect(empty()).toBeNull();
    expect(screen.queryByText(TEXT.generationNoSessions)).toBeNull();
  });
});
