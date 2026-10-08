/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
