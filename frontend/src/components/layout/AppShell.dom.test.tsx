/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { readHint } from "@/test/hint";
import { AppShell } from "./AppShell";
import { usePageTrail } from "./pageTrail";
import { NAV_ITEMS } from "./navLabels";

const state = vi.hoisted(() => ({ admin: false, user: { username: "studio" } as Record<string, unknown> }));
vi.mock("@/api/client", async (original) => ({ ...await original<typeof import("@/api/client")>(), api: async () => ({ is_deployment_admin: state.admin }) }));
// useIsDeploymentAdmin 用真的:它问的是 /api/auth/me,而上面那个 api 桩按 state.admin 回话 ——
// 「管理员才看得到管理」这条就是从那一问开始的,桩掉它等于跳过了要测的东西。
vi.mock("@/app/auth", async (original) => ({
  ...(await original<typeof import("@/app/auth")>()),
  useAuth: () => ({ user: state.user, logout: vi.fn() }),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ theme: "light", locale: "zh-CN", setTheme: vi.fn(), setLocale: vi.fn() }),
}));

beforeEach(() => { state.admin = false; state.user = { username: "studio" }; localStorage.clear(); });

function mount(overrides: Partial<React.ComponentProps<typeof AppShell>> = {}) {
  const navigate = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <TooltipProvider><AppShell view="home" onViewChange={navigate} workspaceName="Studio" projectName={null} {...overrides}>
      <button>Existing workspace content</button>
    </AppShell></TooltipProvider>
  </QueryClientProvider>);
  return navigate;
}

it("keeps every regular view reachable when navigation is expanded or collapsed", () => {
  const navigate = mount();
  for (const collapse of [false, true]) {
    if (collapse) fireEvent.click(screen.getByRole("button", { name: "navCollapse" }));
    for (const item of NAV_ITEMS.filter(item => item.view !== "admin")) {
      fireEvent.click(screen.getByRole("button", { name: item.labelKey }));
      expect(navigate).toHaveBeenLastCalledWith(item.view);
    }
    expect(screen.getByRole("button", { name: "Existing workspace content" })).toBeVisible();
  }
  expect(localStorage.getItem("mosael.sidebar.collapsed")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "navExpand" }));
  expect(screen.getByRole("button", { name: "navCollapse" })).toHaveAttribute("aria-expanded", "true");
});

it("does not expose deployment administration to ordinary users", async () => {
  mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "navHome" })).toBeVisible());
  expect(screen.queryByRole("button", { name: "navAdmin" })).not.toBeInTheDocument();
});

it("preserves administration for deployment admins and restores compact navigation", async () => {
  state.admin = true;
  localStorage.setItem("mosael.sidebar.collapsed", "true");
  const navigate = mount();
  fireEvent.click(await screen.findByRole("button", { name: "navAdmin" }));
  expect(navigate).toHaveBeenLastCalledWith("admin");
  expect(screen.getByRole("button", { name: "navExpand" })).toHaveAttribute("aria-expanded", "false");
});

it("keeps workspace switching and management reachable from both sidebar sizes", async () => {
  const select = vi.fn();
  mount({ workspaces: [
    { id: "a", name: "Studio", role: "owner" },
    { id: "b", name: "Second studio", role: "viewer" },
  ] as React.ComponentProps<typeof AppShell>["workspaces"], onSelectWorkspace: select });
  for (const compact of [false, true]) {
    if (compact) fireEvent.click(screen.getByRole("button", { name: "navCollapse" }));
    fireEvent.click(screen.getByRole("button", { name: "workspaceSwitch" }));
    const popup = await screen.findByRole("menu", { name: "workspaceSwitch" });
    expect(within(popup).getByRole("button", { name: "rename: Studio" })).toBeEnabled();
    expect(within(popup).getByRole("button", { name: "rename: Second studio" })).toBeDisabled();
    expect(within(popup).getByRole("button", { name: "delete: Second studio" })).toBeDisabled();
    // 灰掉的按钮说原因(和设置页同一份门槛,见 workspaceMenu)
    expect(await readHint(within(popup).getByRole("button", { name: "rename: Second studio" }))).toContain("workspaceRenameNeedsAdmin");
    expect(await readHint(within(popup).getByRole("button", { name: "delete: Second studio" }))).toContain("workspaceDeleteNeedsOwner");
    expect(await readHint(within(popup).getByRole("button", { name: "delete: Studio" }))).toBe("delete: Studio");
    expect(within(popup).getByRole("menuitem", { name: "workspaceNew" })).toBeEnabled();
    fireEvent.change(within(popup).getByRole("textbox", { name: "workspaceSearch" }), { target: { value: "Second" } });
    expect(within(popup).queryByRole("button", { name: "rename: Studio" })).not.toBeInTheDocument();
    fireEvent.click(within(popup).getByRole("menuitemradio", { name: "Second studio" }));
    expect(select).toHaveBeenLastCalledWith("b");
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
  }
});

it("子页面交上来的路径接在顶栏的页面名后面:前面几段点得回去,最后一段是「你在这儿」;离开就清掉", () => {
  const onRoot = vi.fn();
  const onParent = vi.fn();
  function Detail() {
    usePageTrail({ onRoot, segments: [{ label: "小美", onSelect: onParent }, { label: "中年" }] });
    return <p>detail</p>;
  }
  function Page({ open }: { open: boolean }) {
    return open ? <Detail /> : <p>list</p>;
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const shell = (open: boolean) => (
    <QueryClientProvider client={client}>
      <TooltipProvider><AppShell view="entities" onViewChange={vi.fn()} workspaceName="Studio" projectName={null}>
        <Page open={open} />
      </AppShell></TooltipProvider>
    </QueryClientProvider>
  );
  const { rerender } = render(shell(true));
  const header = screen.getByRole("banner");
  fireEvent.click(within(header).getByRole("button", { name: "navEntities" }));
  expect(onRoot).toHaveBeenCalled();
  fireEvent.click(within(header).getByRole("button", { name: "小美" }));
  expect(onParent).toHaveBeenCalled();
  expect(within(header).getByText("中年").getAttribute("aria-current")).toBe("page");
  expect(within(header).queryByRole("button", { name: "中年" })).toBeNull();

  rerender(shell(false));
  expect(within(header).queryByText("小美")).toBeNull();
  expect(within(header).queryByRole("button", { name: "navEntities" })).toBeNull();
});

it("账号菜单说出账号从哪来;「账号设置」直达设置里的账号那一节,而不是上次停留的分区", async () => {
  state.user = { username: "ada", oauth_providers: ["google"] };
  mount();
  fireEvent.click(screen.getByRole("button", { name: "ada" }));
  const popup = await screen.findByRole("menu", { name: "ada" });
  // 文案表被桩成原样回 key:两半都在,说明服务器那一半和登录方式那一半都接上了。
  expect(within(popup).getByText("railLocalAccount · railSignedInWith")).toBeVisible();
  expect(within(popup).queryByText(/^@ada · /)).toBeNull();

  const opened = vi.fn();
  const listener = (event: Event) => opened((event as CustomEvent<string>).detail);
  window.addEventListener("mosael:open-settings", listener);
  fireEvent.click(within(popup).getByRole("menuitem", { name: "railAccountSettings" }));
  window.removeEventListener("mosael:open-settings", listener);
  expect(window.location.hash).toBe("#/settings");
  expect(opened).toHaveBeenCalledWith("account");
});

//: 只读成员(体检 UM-20 / D62)建不了项目:顶栏项目切换器里那条是灰的、说清为什么;切换项目照常。
it("只读成员:项目切换器里「新建项目」是灰的并说为什么,切换照常", async () => {
  const create = vi.fn();
  const switchTo = vi.fn();
  mount({
    view: "editor",
    projectName: "片子 A",
    projects: [{ id: "a", name: "片子 A" }, { id: "b", name: "片子 B" }],
    currentProjectId: "a",
    onSwitchProject: switchTo,
    onCreateProject: create,
    createProjectBlocked: "roleReadOnlyBrief",
  });
  fireEvent.click(screen.getByRole("button", { name: "timelineSwitch" }));
  const menu = await screen.findByRole("menu", { name: "timelineSwitch" });
  const item = within(menu).getByRole("menuitem", { name: "createProject" });
  expect(item).toBeDisabled();
  expect(item).toHaveAccessibleDescription("roleReadOnlyBrief");
  fireEvent.click(within(menu).getByRole("menuitemradio", { name: "片子 B" }));
  expect(switchTo).toHaveBeenCalledWith("b");
  expect(create).not.toHaveBeenCalled();
});

/**
 * 工作区切换器里的一行(维护者截图:悬停底色只盖住名字,右边铅笔和垃圾桶落在高亮外面)。
 *
 * 行那一层的样子(圆角、悬停底色、选中底色)全写在**最外层**那一格 `[data-workspace-row]` 上,
 * 里面的 MenuItem 拿同名变体把它自己那层压回透明。布局类是照 class 判的 —— jsdom 没有排版,
 * 量不出来;真的量到过的是首字那 3px(见下面那条),量法写在 components/ui/menu.tsx 的图标槽上。
 */
const WORKSPACES = [
  { id: "a", name: "Studio", role: "owner" },
  { id: "b", name: "Second studio", role: "owner" },
] as React.ComponentProps<typeof AppShell>["workspaces"];

async function openWorkspaceMenu(overrides: Partial<React.ComponentProps<typeof AppShell>> = {}) {
  //: 一条用例里要开三次菜单(三颗按钮各一次),上一次那套外壳得先拆掉 —— 不拆的话
  //: 侧栏里会有两个「workspaceSwitch」按钮。
  cleanup();
  const select = vi.fn();
  mount({ workspaceId: "a", workspaces: WORKSPACES, onSelectWorkspace: select, ...overrides });
  fireEvent.click(screen.getByRole("button", { name: "workspaceSwitch" }));
  const popup = await screen.findByRole("menu", { name: "workspaceSwitch" });
  /** 菜单里的搜索框留在注册表里才叫「顺带检查过」:它在行那一层之外,不该被这一改牵连。 */
  const search = within(popup).getByRole("textbox", { name: "workspaceSearch" });
  expect(search).toBeVisible();
  expect(within(popup).getByRole("menuitem", { name: "workspaceNew" })).toBeVisible();
  return { popup, select };
}

it("悬停底色铺在整行那一格上,而不是名字那一段", async () => {
  const { popup } = await openWorkspaceMenu();
  const rows = within(popup).getAllByRole("menuitemradio");
  expect(rows).toHaveLength(2);
  const row = rows[1]!.closest("[data-workspace-row]")!;
  // 整行那一格:悬停底色在它身上(右边的铅笔和垃圾桶是它的孩子,一起被盖住)。
  expect(row).toHaveClass("hover:bg-secondary");
  expect(within(row as HTMLElement).getByRole("button", { name: "rename: Second studio" })).toBeVisible();
  expect(within(row as HTMLElement).getByRole("button", { name: "delete: Second studio" })).toBeVisible();
  // 名字那一颗自己**不画**底色:两条都在就会叠出第二层(而且只盖住名字那一段,就是截图里那个样子)。
  expect(rows[1]).not.toHaveClass("hover:bg-secondary");
  expect(rows[1]).toHaveClass("hover:bg-transparent");
  // 键盘走到这一行时也一样:一层,在外层。
  expect(row).toHaveClass("has-[:focus-visible]:bg-secondary");
  expect(rows[1]).toHaveClass("focus:bg-transparent");
});

it("选中那一行的底色在外层那一格上,和悬停那一层不是同一条", async () => {
  const { popup } = await openWorkspaceMenu();
  const rows = within(popup).getAllByRole("menuitemradio");
  const selected = rows[0]!.closest("[data-workspace-row]")!;
  const other = rows[1]!.closest("[data-workspace-row]")!;
  expect(selected).toHaveClass("bg-accent");
  expect(other).not.toHaveClass("bg-accent");
  // 选中比悬停重一档(仓库既有的一对:选中 bg-accent、悬停 bg-secondary)——
  // 选中的那一行悬停时不许掉到悬停那一档上。
  expect(selected).toHaveClass("hover:bg-accent");
  expect(selected).not.toHaveClass("hover:bg-secondary");
  // 而它里面的名字那一颗,两种底色都不画。
  expect(rows[0]).not.toHaveClass("bg-accent");
  expect(rows[0]).not.toHaveClass("hover:bg-secondary");
});

it("点名字切工作区、点铅笔开改名、点垃圾桶开删除 —— 三颗互不牵连", async () => {
  const first = await openWorkspaceMenu();
  fireEvent.click(within(first.popup).getByRole("button", { name: "rename: Studio" }));
  await waitFor(() => expect(screen.getByRole("dialog", { name: "renameWorkspace" })).toBeVisible());
  // 铅笔只开改名:没顺手把工作区切走。
  expect(first.select).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("dialog", { name: "renameWorkspace" })).getByRole("button", { name: "cancel" }));

  const second = await openWorkspaceMenu();
  fireEvent.click(within(second.popup).getByRole("button", { name: "delete: Studio" }));
  await waitFor(() => expect(screen.getByRole("alertdialog", { name: "deleteWorkspace" })).toBeVisible());
  expect(second.select).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("alertdialog", { name: "deleteWorkspace" })).getByRole("button", { name: "cancel" }));

  const third = await openWorkspaceMenu();
  fireEvent.click(within(third.popup).getByRole("menuitemradio", { name: "Second studio" }));
  // 名字那一颗才是「切到那个工作区」:只调一次。
  expect(third.select).toHaveBeenCalledTimes(1);
  expect(third.select).toHaveBeenCalledWith("b");
});

//: 真机上量到的:图标槽是 leading-5 的 20px 行盒,10px 的首字放进去偏下 3px(CJK「默」和拉丁「d」都是);
//: 加上 leading-none 之后是 0。只量到一次,之后按 class 守着它。
it("工作区头像那一格:首字在正中", async () => {
  const { popup } = await openWorkspaceMenu();
  const avatar = popup.querySelector('[data-menu-icon] > span')!;
  expect(avatar.textContent).toBe("S");
  expect(avatar).toHaveClass("grid", "size-4", "place-items-center", "leading-none", "text-[10px]");
  // 行盒就是字号本身,不再是被继承来的 leading-5(那正是偏下 3px 的来源)。
  expect(avatar).not.toHaveClass("leading-5");
});

