/** @vitest-environment jsdom */
/**
 * 统计页 —— 它曾经和首页住在 features/home 下,专用图表还叫 HomeCharts(首页并不用它)。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Workspace } from "@/api/client";
import { StatisticsView } from "./StatisticsView";

const mocks = vi.hoisted(() => ({ summary: vi.fn(), assets: [] as unknown[], section: vi.fn(), settings: vi.fn() }));
vi.mock("@/api/client", async original => ({
  ...await original<typeof import("@/api/client")>(),
  workspaceSummary: mocks.summary,
  api: async (path: string) => path.startsWith("/api/assets") ? mocks.assets : { text: "A quiet moment", author: "Studio", source: "" },
  assetThumbnailUrl: (id: string) => `/thumbnail/${id}`,
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("@/lib/deepLink", () => ({ gotoSection: mocks.section, gotoSettings: mocks.settings }));
vi.mock("./StatisticsCharts", () => ({
  ActivityChart: () => <div>Activity chart</div>, AssetKindsChart: () => <div>Asset chart</div>,
  PublishActivityChart: () => <div>Publishing chart</div>, PublishPlatformsChart: () => <div>Platforms chart</div>,
  UsageCostChart: () => <div>Cost chart</div>, UsageTokensChart: () => <div>Tokens chart</div>,
  UsageByProvider: () => <div>Provider chart</div>,
}));
const workspace = { id: "studio-a", name: "Studio A" } as Workspace;
function provider(children: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); mocks.assets = []; });

const SUMMARY = { project_count: 2, asset_count: 3, sequence_count: 1, workflow_count: 4, running_jobs: 5, usage_event_count: 6, usage_cost_micros: 12_340_000, usage_currency: "USD", week_jobs_succeeded: 7, week_published: 8, usage_unknown_cost_events: 0, week_jobs_failed: 0, usage_cache_hit_ratio: 0 };

it("keeps the full statistics overview scoped to the workspace", async () => {
  mocks.summary.mockResolvedValue(SUMMARY);
  const view = render(provider(<StatisticsView workspace={workspace} />));
  await screen.findByRole("button", { name: /homeStatProjects/ });
  expect(mocks.summary).toHaveBeenCalledWith("studio-a");
  expect(screen.getAllByText(/chart$/)).toHaveLength(7);
  // **AI 用量那块磁贴显示的是钱,不是次数。** 它此前显示 usage_event_count(6),而同一个
  // 回包里就躺着 usage_cost_micros —— 而"这个月花了多少"才是打开首页想知道的那个数。
  const usage = screen.getByText("homeStatAiUsage").closest("[data-stat]")!;
  expect(usage).toHaveTextContent("12.34 USD");
  expect(usage).not.toHaveTextContent(/\b6\b/);
  view.rerender(provider(<StatisticsView workspace={{ ...workspace, id: "studio-b" }} />));
  await waitFor(() => expect(mocks.summary).toHaveBeenCalledWith("studio-b"));
});

// 每格去哪儿、哪几格不去(理由见 StatisticsView 里 StatTile 的说明)。都走「从页面起点进来」:
// 此前工作流那格落进的是上次开着的那条工作流详情。
it("links only the tiles that have a list explaining their number, each to that list's root", async () => {
  mocks.summary.mockResolvedValue(SUMMARY);
  const tasks = vi.fn();
  window.addEventListener("mosael:open-tasks", tasks);
  render(provider(<StatisticsView workspace={workspace} />));
  await screen.findByRole("button", { name: /homeStatProjects/ });

  for (const [label, args] of [
    ["Projects", ["home"]],
    ["Assets", ["media"]],
    ["Workflows", ["workflows"]],
    ["WeekPublished", ["publish", "succeeded"]],
  ] as const) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`homeStat${label}`) }));
    expect(mocks.section).toHaveBeenLastCalledWith(...args);
  }
  fireEvent.click(screen.getByRole("button", { name: /homeStatRunningJobs/ }));
  expect(tasks).toHaveBeenCalledTimes(1);
  window.removeEventListener("mosael:open-tasks", tasks);
  expect(screen.getAllByRole("button")).toHaveLength(5);

  // 序列没有列表页;AI 用量、近 7 天完成的解释就在本页下方的图里 —— 只是读数,不装作能点。
  for (const key of ["homeStatSequences", "homeStatAiUsage", "homeStatWeekDone"]) {
    const tile = screen.getByText(key).closest("[data-stat]")!;
    expect(tile.tagName).toBe("DIV");
    expect(tile).not.toHaveAttribute("role");
    expect(tile.className).not.toMatch(/cursor-pointer|hover:/);
    fireEvent.click(tile);
  }
  expect(mocks.section).toHaveBeenCalledTimes(4);
  expect(mocks.settings).not.toHaveBeenCalled();
});

it("sends the unpriced count to the pricing rules, and leaves the failed count as a reading", async () => {
  mocks.summary.mockResolvedValue({ ...SUMMARY, usage_unknown_cost_events: 3, week_jobs_failed: 2 });
  render(provider(<StatisticsView workspace={workspace} />));
  const unpriced = await screen.findByRole("button", { name: "homeStatUsageUnknownSuffix" });
  expect(unpriced).toHaveAttribute("title", "homeChartUsageConfigurePricing");
  fireEvent.click(unpriced);
  expect(mocks.settings).toHaveBeenCalledWith("provider-pricing");
  expect(screen.getByText("homeStatWeekDone").closest("[data-stat]")).toHaveTextContent("homeStatWeekFailedSuffix");
  expect(screen.queryByRole("button", { name: /homeStatWeekFailedSuffix/ })).toBeNull();
});

it("shows a recoverable statistics error instead of an empty dashboard", async () => {
  mocks.summary.mockRejectedValue(new Error("Unavailable"));
  render(provider(<StatisticsView workspace={workspace} />));
  expect(await screen.findByRole("alert")).toHaveTextContent("statsUnavailable");
  const calls = mocks.summary.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(mocks.summary.mock.calls.length).toBeGreaterThan(calls));
});
