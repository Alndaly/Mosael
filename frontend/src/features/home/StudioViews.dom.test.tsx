/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { Asset, ProjectWithStats, Workspace } from "@/api/client";
import { StatisticsView } from "./StatisticsView";
import { HomeView } from "./HomeView";

const mocks = vi.hoisted(() => ({ summary: vi.fn(), assets: [] as unknown[], navigate: vi.fn() }));
vi.mock("@/api/client", async original => ({
  ...await original<typeof import("@/api/client")>(),
  workspaceSummary: mocks.summary,
  api: async (path: string) => path.startsWith("/api/assets") ? mocks.assets : { text: "A quiet moment", author: "Studio", source: "" },
  assetThumbnailUrl: (id: string) => `/thumbnail/${id}`,
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("@/lib/deepLink", () => ({ gotoRecord: mocks.navigate }));
vi.mock("./HomeHero", () => ({ HomeHero: () => <div>Daily poem</div> }));
vi.mock("./HomeCharts", () => ({
  ActivityChart: () => <div>Activity chart</div>, AssetKindsChart: () => <div>Asset chart</div>,
  PublishActivityChart: () => <div>Publishing chart</div>, PublishPlatformsChart: () => <div>Platforms chart</div>,
  UsageCostChart: () => <div>Cost chart</div>, UsageTokensChart: () => <div>Tokens chart</div>,
}));
const workspace = { id: "studio-a", name: "Studio A" } as Workspace;
const projects = [
  { id: "older", name: "Older film", updated_at: "2026-09-01", created_at: "2026-08-01" },
  { id: "newer", name: "Newer film", updated_at: "2026-09-06", created_at: "2026-09-01" },
] as ProjectWithStats[];
function provider(children: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); mocks.assets = []; });

it("keeps the full statistics overview scoped to the workspace and preserves all destinations", async () => {
  mocks.summary.mockResolvedValue({ project_count: 2, asset_count: 3, sequence_count: 1, workflow_count: 4, running_jobs: 5, usage_event_count: 6, week_jobs_succeeded: 7, week_published: 8, usage_unknown_cost_events: 0, week_jobs_failed: 0, usage_cache_hit_ratio: 0 });
  const open = vi.fn();
  const tasks = vi.fn();
  window.addEventListener("mosael:open-tasks", tasks);
  const view = render(provider(<StatisticsView workspace={workspace} projects={projects} onOpenProject={open} />));
  await screen.findByRole("button", { name: /homeStatProjects/ });
  expect(mocks.summary).toHaveBeenCalledWith("studio-a");
  expect(screen.getAllByRole("button")).toHaveLength(8);
  expect(screen.getAllByText(/chart$/)).toHaveLength(6);
  for (const [label, path] of [["Projects", "/home"], ["Assets", "/media"], ["Workflows", "/workflows"], ["AiUsage", "/ai"], ["WeekPublished", "/publish"]]) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`homeStat${label}`) }));
    expect(mocks.navigate).toHaveBeenLastCalledWith(path);
  }
  fireEvent.click(screen.getByRole("button", { name: /homeStatSequences/ }));
  expect(open).toHaveBeenCalledWith("newer");
  fireEvent.click(screen.getByRole("button", { name: /homeStatRunningJobs/ }));
  fireEvent.click(screen.getByRole("button", { name: /homeStatWeekDone/ }));
  expect(tasks).toHaveBeenCalledTimes(2);
  window.removeEventListener("mosael:open-tasks", tasks);
  view.rerender(provider(<StatisticsView workspace={{ ...workspace, id: "studio-b" }} projects={[]} onOpenProject={open} />));
  await waitFor(() => expect(mocks.summary).toHaveBeenCalledWith("studio-b"));
});

it("shows a recoverable statistics error instead of an empty dashboard", async () => {
  mocks.summary.mockRejectedValue(new Error("Unavailable"));
  render(provider(<StatisticsView workspace={workspace} projects={[]} onOpenProject={vi.fn()} />));
  expect(await screen.findByRole("alert")).toHaveTextContent("statsUnavailable");
  const calls = mocks.summary.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(mocks.summary.mock.calls.length).toBeGreaterThan(calls));
});

it("opens and filters projects in both presentations and only uses their own media", async () => {
  mocks.assets = [
    { id: "unassigned", kind: "image", project_id: null },
    { id: "cover", kind: "image", project_id: "newer" },
  ] as Asset[];
  const open = vi.fn();
  const create = vi.fn();
  const view = render(provider(<HomeView workspace={workspace} projects={projects} onOpenProject={open} onCreateProject={create} creatingProject={false} />));
  await waitFor(() => expect(view.container.querySelector('img[src="/thumbnail/cover"]')).not.toBeNull());
  expect(view.container.querySelector('img[src="/thumbnail/unassigned"]')).toBeNull();
  fireEvent.error(view.container.querySelector('img[src="/thumbnail/cover"]')!);
  fireEvent.click(screen.getByRole("button", { name: "homeOpenEditor: Newer film" }));
  expect(open).toHaveBeenLastCalledWith("newer");
  fireEvent.click(screen.getByRole("button", { name: "homeAll" }));
  fireEvent.click(screen.getByRole("button", { name: "Older film" }));
  expect(open).toHaveBeenLastCalledWith("older");
  fireEvent.change(screen.getByRole("textbox", { name: "searchProjects" }), { target: { value: "newer" } });
  expect(screen.queryByRole("button", { name: "Older film" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "searchProjects" }), { target: { value: "missing" } });
  expect(screen.getByText("homeNoSearchResults")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "createProject" }));
  expect(create).toHaveBeenCalledOnce();
  expect(mocks.summary).not.toHaveBeenCalled();
});
