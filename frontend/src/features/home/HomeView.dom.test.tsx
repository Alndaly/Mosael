/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ProjectWithStats, Workspace } from "@/api/client";
import { HomeView } from "./HomeView";

const mocks = vi.hoisted(() => ({ summary: vi.fn(), navigate: vi.fn(), deleteProject: vi.fn(async (_id: string) => undefined) }));
vi.mock("@/api/client", async original => ({
  ...await original<typeof import("@/api/client")>(),
  workspaceSummary: mocks.summary,
  deleteProject: mocks.deleteProject,
  api: async () => ({ text: "A quiet moment", author: "Studio", source: "" }),
  assetThumbnailUrl: (id: string) => `/thumbnail/${id}`,
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("@/lib/deepLink", () => ({ gotoRecord: mocks.navigate }));
const workspace = { id: "studio-a", name: "Studio A" } as Workspace;
const projects = [
  { id: "older", name: "Older film", updated_at: "2026-09-01", created_at: "2026-08-01" },
  // 封面由后端算好给(时间线上最早出现的画面),卡片只管画。
  { id: "newer", name: "Newer film", updated_at: "2026-09-06", created_at: "2026-09-01", cover_asset_id: "cover" },
] as ProjectWithStats[];
function provider(children: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });

it("opens and filters projects in both presentations and draws the cover the backend picked", async () => {
  const open = vi.fn();
  const create = vi.fn();
  const view = render(provider(<HomeView workspace={workspace} projects={projects} onOpenProject={open} onCreateProject={create} creatingProject={false} />));
  const header = screen.getByRole("banner");
  expect(view.container.firstElementChild?.firstElementChild).toBe(header);
  expect(within(header).getByText("Studio A")).toBeVisible();
  expect(await within(header).findByText("A quiet moment")).toBeVisible();
  expect(within(header).getByRole("button", { name: "homePoemRefresh" })).toBeEnabled();
  expect(within(header).getByRole("button", { name: "createProject" })).toBeEnabled();
  await waitFor(() => expect(view.container.querySelector('img[src="/thumbnail/cover"]')).not.toBeNull());
  expect(view.container.querySelectorAll("img")).toHaveLength(1);
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

it("能批量选中项目一起删 —— 选择模式下点卡片是勾选,不是打开", async () => {
  const open = vi.fn();
  render(provider(<HomeView workspace={workspace} projects={projects} onOpenProject={open} onCreateProject={vi.fn()} creatingProject={false} />));

  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode: Newer film" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode: Older film" }));
  expect(open).not.toHaveBeenCalled();
  expect(screen.getByText("mediaSelectedCount")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "delete" }));
  fireEvent.click(await screen.findByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.deleteProject).toHaveBeenCalledTimes(2));
  expect(mocks.deleteProject.mock.calls.map((call) => call[0]).sort()).toEqual(["newer", "older"]);
});
