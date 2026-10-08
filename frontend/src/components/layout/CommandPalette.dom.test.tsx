/** @vitest-environment jsdom */
/**
 * ⌘K 面板里的三件事:
 * - 「新建项目」真的建一个(和顶栏项目切换器同一个动作),不是跳回首页让人再点一次;
 * - 「切换主题」和顶栏按钮走同一个循环(浅 → 深 → 跟随系统),不在深浅之间两态互切;
 * - 默认高亮按实际渲染顺序取第一项 —— 只搜到工作流时 Enter 也得有目标。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ theme: "dark", setTheme: vi.fn() }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN", theme: h.theme, setTheme: h.setTheme }),
}));
vi.mock("@/app/auth", () => ({ useIsDeploymentAdmin: () => false }));
vi.mock("@/api/client", () => ({
  api: async () => [],
  listWorkflows: async () => [{ id: "wf1", name: "zzqx 周报", description: "", graph: { nodes: [] } }],
  listPublishTasks: async () => [],
  listEntities: async (_ws: string, filters: { q?: string }) =>
    filters.q === "珍珠" ? [{ id: "e1", kind: "character", name: "珍珠耳环少女" }] : [],
  listNotes: async (_ws: string, q: string) => (q === "珍珠" ? [{ id: "n1", title: "珍珠的来历" }] : []),
  listBoards: async () => [{ id: "b1", name: "珍珠分镜" }, { id: "b2", name: "别的" }],
  entityKeys: { catalog: () => ["entity-catalog"], list: (ws: string, filters: unknown) => ["entities", ws, "list", filters] },
  getEntityCatalog: async () => ({ kinds: [{ kind: "character", label: "人物" }], roles: [], roles_by_kind: {}, consent_kinds: [], attach_priority: {} }),
}));
const links = vi.hoisted(() => ({ openNote: vi.fn(), openBoard: vi.fn(), gotoSettings: vi.fn(), gotoAdmin: vi.fn() }));
vi.mock("@/lib/deepLink", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/deepLink")>()),
  openNote: links.openNote,
  openBoard: links.openBoard,
  gotoSettings: links.gotoSettings,
  gotoAdmin: links.gotoAdmin,
}));

import { CommandPalette } from "@/components/layout/CommandPalette";
import { OverNativeView } from "@/components/app/overNativeView";
import { resetNativeViewAside, settleNativeViewAside } from "@/components/ui/nativeViewAside";
import { resetNativeViewForTests } from "@/lib/nativeView";

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
});
beforeEach(() => {
  h.theme = "dark";
  h.setTheme.mockReset();
});

function mount(role = "editor") {
  const onNavigate = vi.fn();
  const onCreateProject = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {/* 和 App 里一样挂在 OverNativeView 里(ADR 0051) */}
      <OverNativeView>
        <CommandPalette
          workspace={{ id: "w1", name: "W", role } as never}
          projects={[]}
          onNavigate={onNavigate}
          onOpenProject={vi.fn()}
          onCreateProject={onCreateProject}
        />
      </OverNativeView>
    </QueryClientProvider>,
  );
  act(() => void window.dispatchEvent(new CustomEvent("mosael:open-cmdk")));
  return { onNavigate, onCreateProject };
}

it("新建项目直接建,不跳首页", async () => {
  const { onNavigate, onCreateProject } = mount();
  fireEvent.click(await screen.findByRole("option", { name: /createProject/ }));
  expect(onCreateProject).toHaveBeenCalledTimes(1);
  expect(onNavigate).not.toHaveBeenCalled();
});

//: 只读成员(体检 UM-20 / D62)建不了项目:面板里一条点不了、又说不出为什么的命令只是噪音,不列;别的照常。
it("只读成员:快捷操作里没有「新建项目」,切换主题照常", async () => {
  mount("viewer");
  expect(await screen.findByRole("option", { name: /cmdkToggleTheme/ })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /createProject/ })).toBeNull();
});

it("切换主题和顶栏同一个循环:深色的下一档是跟随系统", async () => {
  mount();
  const toggle = await screen.findByRole("option", { name: /cmdkToggleTheme/ });
  expect(toggle).toHaveTextContent("themeSystem");
  fireEvent.click(toggle);
  expect(h.setTheme).toHaveBeenCalledWith("system");
});

it("只搜到工作流时,默认高亮落在它身上", async () => {
  mount();
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "zzqx" } });
  const workflow = await screen.findByRole("option", { name: /zzqx 周报/ });
  await waitFor(() => expect(workflow).toHaveAttribute("aria-selected", "true"));
});

//: 体检 UM-14:「全局搜索」此前搜不到资产、笔记、画板和设置项 —— 搜「珍珠耳环」只出来那张图片素材。
it("资产、笔记、画板都搜得到,点了各自打开", async () => {
  const { onNavigate } = mount();
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "珍珠" } });
  const entity = await screen.findByRole("option", { name: /珍珠耳环少女/ });
  expect(entity).toHaveTextContent("人物");
  expect(await screen.findByRole("option", { name: /珍珠的来历/ })).toBeInTheDocument();
  expect(await screen.findByRole("option", { name: /珍珠分镜/ })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /别的/ })).toBeNull();

  fireEvent.click(entity);
  expect(onNavigate).toHaveBeenCalledWith("entities");
});

it("设置项搜得到;只在管理页的,不是部署管理员时看得到但点不了", async () => {
  mount();
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "settingsPassword" } });
  fireEvent.click(await screen.findByRole("option", { name: /settingsAccount/ }));
  expect(links.gotoSettings).toHaveBeenCalledWith("account");

  act(() => void window.dispatchEvent(new CustomEvent("mosael:open-cmdk")));
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "proxyTitle" } });
  const proxy = await screen.findByRole("option", { name: /proxyTitle/ });
  expect(proxy).toHaveTextContent("cmdkAdminOnly");
  expect(proxy).toHaveAttribute("aria-disabled", "true");
});

//: ADR 0051 D36:内嵌浏览器、工作台的画布在前台时 ⌘K 照常能用 —— 面板抬过外壳、开着时请视图让开;选了去别处的那一项,先把视图收起来再走
//: (不然面板一关网页又盖回来,跳过去的那一页在它底下)。换主题人还在原处,不收。
describe("原生视图在前台时的命令面板", () => {
  const order: string[] = [];
  let bridge: { onViewState: unknown; setOverlay: ReturnType<typeof vi.fn>; hideView: ReturnType<typeof vi.fn> };
  beforeEach(() => {
    order.length = 0;
    bridge = {
      onViewState: (callback: (state: { visible: boolean }) => void) => {
        callback({ visible: true });
        return () => undefined;
      },
      setOverlay: vi.fn(async (up: boolean) => void order.push(`overlay:${up}`)),
      hideView: vi.fn(async () => void order.push("hideView")),
    };
    vi.stubGlobal("mosaelPublish", bridge);
    resetNativeViewForTests();
  });
  afterEach(async () => {
    cleanup(); // 先卸掉面板(放开它占的那次让开),再重置
    await settleNativeViewAside();
    resetNativeViewAside();
    vi.unstubAllGlobals();
    resetNativeViewForTests();
  });

  it("面板抬过外壳(z 205),开着时视图让开", async () => {
    mount();
    const panel = await screen.findByRole("dialog");
    expect(panel.className).toMatch(/z-\[205\]/);
    await waitFor(() => expect(order).toEqual(["overlay:true"]));
  });

  it("选了一页:先收起视图,再跳", async () => {
    const { onNavigate } = mount();
    onNavigate.mockImplementation(() => void order.push("navigate"));
    await waitFor(() => expect(order).toEqual(["overlay:true"]));
    fireEvent.click(await screen.findByRole("option", { name: /navMedia|素材|media/i }));
    expect(order.slice(0, 3)).toEqual(["overlay:true", "hideView", "navigate"]);
  });

  it("换主题:人还在原处,不收视图", async () => {
    mount();
    fireEvent.click(await screen.findByRole("option", { name: /cmdkToggleTheme/ }));
    expect(h.setTheme).toHaveBeenCalled();
    expect(bridge.hideView).not.toHaveBeenCalled();
  });
});
