/** @vitest-environment jsdom */
/**
 * 统计页 —— 它曾经和首页住在 features/home 下,专用图表还叫 HomeCharts(首页并不用它)。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  UsageCostPanel: () => <><div>Cost chart</div><div>Provider chart</div></>, UsageTokensChart: () => <div>Tokens chart</div>,
}));
const workspace = { id: "studio-a", name: "Studio A" } as Workspace;
function provider(children: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); mocks.assets = []; });

const SUMMARY = { project_count: 2, asset_count: 3, sequence_count: 1, workflow_count: 4, running_jobs: 5, usage_event_count: 6, usage_costs: [{ currency: "USD", micros: 12_340_000 }], window_days: 30, jobs_succeeded: 7, published: 8, usage_unknown_cost_events: 0, jobs_failed: 0, usage_cache_hit_ratio: 0 };

it("keeps the full statistics overview scoped to the workspace", async () => {
  mocks.summary.mockResolvedValue(SUMMARY);
  const view = render(provider(<StatisticsView workspace={workspace} />));
  await screen.findByRole("button", { name: /homeStatProjects/ });
  expect(mocks.summary).toHaveBeenCalledWith("studio-a", 30);
  // **AI 用量那块磁贴显示的是钱,不是次数。** 它此前显示 usage_event_count(6),而同一个
  // 回包里就躺着金额 —— 而"这个月花了多少"才是打开首页想知道的那个数。
  const usage = screen.getByText("homeStatAiUsage").closest("[data-stat]")!;
  expect(usage).toHaveTextContent("$12.34");
  expect(usage).not.toHaveTextContent(/\b6\b/);
  view.rerender(provider(<StatisticsView workspace={{ ...workspace, id: "studio-b" }} />));
  await waitFor(() => expect(mocks.summary).toHaveBeenCalledWith("studio-b", 30));
});

// 三块回答三个人的问题:做了多少、发出去没有、花了多少。每个 tab 只摆它自己的图,记住上次看的那个。
it("splits the page into overview, publishing and AI usage tabs, each with its own charts", async () => {
  mocks.summary.mockResolvedValue(SUMMARY);
  render(provider(<StatisticsView workspace={workspace} />));
  await screen.findByRole("button", { name: /homeStatProjects/ });
  const charts = () => screen.queryAllByText(/chart$/).map((el) => el.textContent);
  expect(charts()).toEqual(["Activity chart", "Asset chart"]);

  fireEvent.click(screen.getByRole("button", { name: "statsTabPublish" }));
  expect(charts()).toEqual(["Publishing chart", "Platforms chart"]);
  expect(screen.queryByText("homeStatProjects")).toBeNull(); // 读数只在概览

  fireEvent.click(screen.getByRole("button", { name: "statsTabUsage" }));
  expect(charts()).toEqual(["Cost chart", "Provider chart", "Tokens chart"]);
  expect(localStorage.getItem("mosael:tab:statistics")).toBe("usage");
});

// 一个窗口管住整页:换范围就按新窗口重取,读数的标签跟着写「近 N 天」。和管理页同一个控件。
it("refetches for the picked range and labels windowed tiles with it", async () => {
  mocks.summary.mockImplementation(async (_id: string, days: number) => ({ ...SUMMARY, window_days: days }));
  render(provider(<StatisticsView workspace={workspace} />));
  await screen.findByRole("button", { name: /homeStatProjects/ });
  const range = screen.getByRole("radiogroup", { name: "statRangeLabel" });
  fireEvent.click(within(range).getAllByRole("radio")[2]);
  await waitFor(() => expect(mocks.summary).toHaveBeenLastCalledWith("studio-a", 90));
  expect(localStorage.getItem("mosael:tab:statistics-range")).toBe("90");
});

// 人民币和美元**不相加**:磁贴上各写一笔。此前是 16.8 USD —— 一个既不是人民币也不是美元的数。
it("writes one amount per currency on the usage tile instead of a mixed sum", async () => {
  mocks.summary.mockResolvedValue({
    ...SUMMARY,
    usage_costs: [{ currency: "CNY", micros: 12_300_000 }, { currency: "USD", micros: 4_500_000 }],
  });
  render(provider(<StatisticsView workspace={workspace} />));
  await screen.findByRole("button", { name: /homeStatProjects/ });
  const usage = screen.getByText("homeStatAiUsage").closest("[data-stat]")!;
  expect(usage).toHaveTextContent("CN¥12.30 + $4.50");
  expect(usage).not.toHaveTextContent("16.8");
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
    ["Published", ["publish", "succeeded"]],
  ] as const) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`homeStat${label}`) }));
    expect(mocks.section).toHaveBeenLastCalledWith(...args);
  }
  fireEvent.click(screen.getByRole("button", { name: /homeStatRunningJobs/ }));
  expect(tasks).toHaveBeenCalledTimes(1);
  window.removeEventListener("mosael:open-tasks", tasks);
  const tiles = screen.getByText("homeStatProjects").closest("section")!;
  expect(within(tiles).getAllByRole("button")).toHaveLength(5);

  // 序列没有列表页;AI 花费、近 N 天完成的解释就在本页的图里 —— 只是读数,不装作能点。
  for (const key of ["homeStatSequences", "homeStatAiUsage", "homeStatJobsDone"]) {
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
  mocks.summary.mockResolvedValue({ ...SUMMARY, usage_unknown_cost_events: 3, jobs_failed: 2 });
  render(provider(<StatisticsView workspace={workspace} />));
  const unpriced = await screen.findByRole("button", { name: "homeStatUsageUnknownSuffix" });
  expect(unpriced).toHaveAttribute("title", "homeChartUsageConfigurePricing");
  fireEvent.click(unpriced);
  expect(mocks.settings).toHaveBeenCalledWith("provider-pricing");
  expect(screen.getByText("homeStatJobsDone").closest("[data-stat]")).toHaveTextContent("homeStatJobsFailedSuffix");
  expect(screen.queryByRole("button", { name: /homeStatJobsFailedSuffix/ })).toBeNull();
});

it("shows a recoverable statistics error instead of an empty dashboard", async () => {
  mocks.summary.mockRejectedValue(new Error("Unavailable"));
  render(provider(<StatisticsView workspace={workspace} />));
  expect(await screen.findByRole("alert")).toHaveTextContent("statsUnavailable");
  const calls = mocks.summary.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(mocks.summary.mock.calls.length).toBeGreaterThan(calls));
});
