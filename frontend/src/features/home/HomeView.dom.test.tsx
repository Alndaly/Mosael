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
  api: async (path: string, init?: { body?: string }) =>
    path === "/api/projects"
      ? { id: "brand-new", workspace_id: "studio-a", name: JSON.parse(init?.body ?? "{}").name, active_sequence_id: null }
      : { text: "A quiet moment", author: "Studio", source: "" },
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
const loaded = { pending: false, error: null, retrying: false, retry: vi.fn() };
function provider(children: React.ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{children}</QueryClientProvider>;
}
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });

it("opens and filters projects in both presentations and draws the cover the backend picked", async () => {
  const open = vi.fn();
  const view = render(provider(<HomeView workspace={workspace} projects={projects} load={loaded} onOpenProject={open} />));
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
  // 新建:先弹窗起名,建好留在首页,不跳走。
  fireEvent.click(screen.getByRole("button", { name: "createProject" }));
  const naming = await screen.findByRole("dialog");
  fireEvent.change(within(naming).getByRole("textbox"), { target: { value: "My new film" } });
  fireEvent.click(within(naming).getByRole("button", { name: "createProjectConfirm" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(open).not.toHaveBeenCalledWith("brand-new");
  expect(mocks.summary).not.toHaveBeenCalled();
});

it("能批量选中项目一起删 —— 选择模式下点卡片是勾选,不是打开", async () => {
  const open = vi.fn();
  render(provider(<HomeView workspace={workspace} projects={projects} load={loaded} onOpenProject={open} />));

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

it("选择模式下点这一行的空白处也能勾上", () => {
  render(provider(<HomeView workspace={workspace} projects={projects} load={loaded} onOpenProject={vi.fn()} />));
  fireEvent.click(screen.getByRole("button", { name: "homeAll" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
  const row = screen.getByRole("button", { name: "mediaSelectMode: Older film" }).closest("article")!;
  fireEvent.click(row);
  expect(row).toHaveAttribute("aria-selected", "true");
  // 点封面本身:只翻一次,不会勾上又立刻取消。
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode: Older film" }));
  expect(row).toHaveAttribute("aria-selected", "false");
});

it("点这一行的空白处就打开项目;点「…」菜单不会顺带打开", () => {
  const open = vi.fn();
  render(provider(<HomeView workspace={workspace} projects={projects} load={loaded} onOpenProject={open} />));
  fireEvent.click(screen.getByRole("button", { name: "homeAll" }));
  const row = screen.getByRole("button", { name: "homeOpenEditor: Older film" }).closest("article")!;
  fireEvent.click(row);
  expect(open).toHaveBeenLastCalledWith("older");
  expect(open).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole("button", { name: "projectActions: Older film" }));
  expect(open).toHaveBeenCalledTimes(1);
});

it("刚建好的项目亮的样子和选中一样:卡片圈封面、列表行铺底,不在整张卡外面再套一圈", async () => {
  const view = render(provider(<HomeView workspace={workspace} projects={projects} load={loaded} onOpenProject={vi.fn()} />));
  fireEvent.click(screen.getByRole("button", { name: "createProject" }));
  const naming = await screen.findByRole("dialog");
  fireEvent.click(within(naming).getByRole("button", { name: "createProjectConfirm" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const created = { id: "brand-new", name: "Brand new", updated_at: "2026-09-24", created_at: "2026-09-24" } as ProjectWithStats;
  view.rerender(provider(<HomeView workspace={workspace} projects={[created, ...projects]} load={loaded} onOpenProject={vi.fn()} />));

  const card = view.container.querySelector('[data-project-id="brand-new"]')!;
  expect(card.className).not.toMatch(/\bring-/);
  expect(within(card as HTMLElement).getByRole("button", { name: "homeOpenEditor: Brand new" })).toHaveClass("ring-2", "ring-primary");

  fireEvent.click(screen.getByRole("button", { name: "homeAll" }));
  const row = view.container.querySelector('[data-project-id="brand-new"]')!;
  expect(row.className).not.toMatch(/\bring-/);
  expect(row.className).toContain("var(--primary)_8%");
});

//: 和时间线同一条规则:右键的那一项在选区里,菜单作用于整个选区、只给能对一批做的动作;不在,就只是它自己。
//: 此前多选着右键一项,菜单给的是单条的重命名 / 删除 —— 看着像批量删,实际只删了被点的那一条。
it("多选时右键选区里的一项:菜单作用于整个选区;右键选区外的一项只作用于它自己", async () => {
  render(provider(<HomeView workspace={workspace} projects={projects} load={loaded} onOpenProject={vi.fn()} />));
  fireEvent.click(screen.getByRole("button", { name: "homeAll" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode" }));
  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode: Older film" }));

  //: 选区里只有它一个:照旧是它自己的菜单。
  fireEvent.contextMenu(screen.getByRole("button", { name: "Newer film" }), { clientX: 10, clientY: 10 });
  expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["homeOpenEditor", "rename", "delete"]);
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

  fireEvent.click(screen.getByRole("button", { name: "mediaSelectMode: Newer film" }));
  fireEvent.contextMenu(screen.getByRole("button", { name: "Newer film" }), { clientX: 10, clientY: 10 });
  expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["deleteSelectedN"]);
  fireEvent.click(screen.getByRole("menuitem", { name: "deleteSelectedN" }));
  fireEvent.click(await screen.findByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.deleteProject).toHaveBeenCalledTimes(2));
  expect(mocks.deleteProject.mock.calls.map((call) => call[0]).sort()).toEqual(["newer", "older"]);
});

//: 排序方式跟着人走:「最近」那一栏本来就按更新时间排,切过去不能顺手把人选的排序改掉。
it("切到「最近」再回「全部」,排序还是人选的那一种", () => {
  localStorage.setItem("mosael:tab:home-collection", "all");
  localStorage.setItem("mosael:tab:home-sort", "name");
  render(provider(<HomeView workspace={workspace} projects={projects} load={loaded} onOpenProject={vi.fn()} />));
  fireEvent.click(screen.getByRole("button", { name: "homeRecent" }));
  expect(localStorage.getItem("mosael:tab:home-sort")).toBe("name");
  fireEvent.click(screen.getByRole("button", { name: "homeAll" }));
  expect(screen.getByRole("combobox", { name: "sortUpdated" })).toHaveTextContent("sortName");
});

//: 体检 UM-21:项目列表取不回来时,此前也是「还没有项目 / 新建一个项目」—— 后端瞬断、升级重启时看着像项目全丢了。
it("项目没取回来时说没取回来、能重试,不说「还没有项目」;取回来是空的才说", () => {
  const retry = vi.fn();
  const view = render(provider(
    <HomeView workspace={workspace} projects={[]} load={{ pending: false, error: new Error("boom"), retrying: false, retry }} onOpenProject={vi.fn()} />,
  ));
  expect(screen.queryByText("homeEmptyTitle")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(retry).toHaveBeenCalled();

  view.rerender(provider(<HomeView workspace={workspace} projects={[]} load={{ ...loaded, pending: true }} onOpenProject={vi.fn()} />));
  expect(screen.queryByText("homeEmptyTitle")).toBeNull();

  view.rerender(provider(<HomeView workspace={workspace} projects={[]} load={loaded} onOpenProject={vi.fn()} />));
  expect(screen.getByText("homeEmptyTitle")).toBeTruthy();
});

//: 体检 UM-30:英文首页「1 sequences」。一个就用单数那条。
it("项目卡上的序列数一个时用单数那条文案", () => {
  localStorage.setItem("mosael:tab:home-collection", "all");
  render(provider(
    <HomeView workspace={workspace} projects={[{ ...projects[0], sequence_count: 1 }, { ...projects[1], sequence_count: 2 }]} load={loaded} onOpenProject={vi.fn()} />,
  ));
  expect(screen.getAllByText("projectStatSequence").length).toBeGreaterThan(0);
  expect(screen.getAllByText("projectStatSequences").length).toBeGreaterThan(0);
});

it("轮询中途失败、手上还有上一份时照旧列项目", () => {
  render(provider(
    <HomeView workspace={workspace} projects={projects} load={{ ...loaded, error: new Error("boom") }} onOpenProject={vi.fn()} />,
  ));
  expect(screen.getAllByText("Newer film").length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
});
