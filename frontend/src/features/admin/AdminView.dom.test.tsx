/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 管理页:三个 tab 各自有哪几节、节与节**不可能叠在一起**、以及每一处会改东西的动作真的打到后端。
 *
 * 走真正的组件(只替掉接口和图表),不去测抽出来的字符串拼接函数:错常常发生在
 * "接口字段 → 屏幕上那行字"这一跳上,而那正是绕过组件就测不到的一跳。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("./AdminActivityChart", () => ({ AdminActivityChart: () => null }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/deepLink", () => ({ gotoSettings: vi.fn() }));

const rows: Array<Record<string, unknown>> = [];
let overview: Record<string, unknown> = { spend_by_user: [], jobs_by_day: [], costs: [], window_days: 30 };
let openRegistration = true;
const calls = {
  overview: vi.fn(),
  setAdmin: vi.fn(),
  deleteAccount: vi.fn(),
  setOpenRegistration: vi.fn(),
  createInvite: vi.fn(),
};
vi.mock("@/api/client", () => ({
  adminOverview: (days: number) => {
    calls.overview(days);
    return Promise.resolve({ ...overview, window_days: days });
  },
  adminUsers: () => Promise.resolve(rows),
  setDeploymentAdmin: (id: string, granted: boolean) => {
    calls.setAdmin(id, granted);
    return Promise.resolve({});
  },
  deleteAccount: (id: string) => {
    calls.deleteAccount(id);
    return Promise.resolve();
  },
  authBootstrap: () => Promise.resolve({ has_users: true, open_registration: openRegistration }),
  setOpenRegistration: (open: boolean) => {
    calls.setOpenRegistration(open);
    openRegistration = open;
    return Promise.resolve({ open });
  },
  registrationInvites: () => Promise.resolve([{ code: "CODE1", note: "for **Sam**", used: false, expires_at: "2099-01-01T00:00:00Z" }]),
  createRegistrationInvite: (note: string) => {
    calls.createInvite(note);
    return Promise.resolve({ code: "NEW", note, used: false, expires_at: "2099-01-01T00:00:00Z" });
  },
  getSharedHostFolders: () => Promise.resolve({ folders: [] }),
  setSharedHostFolders: (folders: string[]) => Promise.resolve({ folders }),
}));

const { AdminView } = await import("./AdminView");

function show(people: Array<Record<string, unknown>> = [], tab?: "overview" | "members" | "deployment") {
  rows.length = 0;
  rows.push(...people);
  if (tab) localStorage.setItem("mosael:tab:admin", tab);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminView />
    </QueryClientProvider>,
  );
}

const base = {
  id: "u1",
  username: "demo",
  display_name: "Demo",
  is_deployment_admin: false,
  created_at: "2026-09-01T00:00:00Z",
  last_seen_at: "2026-09-22T00:00:00Z",
  workspaces: 1,
  client_surface: "app",
  client_version: "1.5.2",
};
const admin = { ...base, id: "a1", username: "boss", display_name: "Boss", is_deployment_admin: true };

beforeEach(() => {
  localStorage.clear();
  openRegistration = true;
  overview = { spend_by_user: [], jobs_by_day: [], costs: [], window_days: 30 };
  for (const fn of Object.values(calls)) fn.mockClear();
});

/** 页面上画出来的节,按出现顺序。 */
function sections(container: HTMLElement) {
  return [...container.querySelectorAll<HTMLElement>("[data-admin-section]")].map((el) => el.dataset.adminSection);
}

describe("结构", () => {
  it("三个 tab 各有自己的几节,切换只换内容区", async () => {
    const { container } = show([admin, base]);
    await screen.findByText("adminStatUsers");
    expect(sections(container)).toEqual(["range", "stats", "activity", "spend"]);

    fireEvent.click(screen.getByRole("button", { name: "adminTabMembers" }));
    await screen.findByText("Demo");
    expect(sections(container)).toEqual(["accounts", "invites"]);

    fireEvent.click(screen.getByRole("button", { name: "adminTabDeployment" }));
    await screen.findByRole("switch", { name: "deployRegistrationOpen" });
    expect(sections(container)).toEqual(["registration", "shared-folders"]);
    // 选中的 tab 活过导航。
    expect(localStorage.getItem("mosael:tab:admin")).toBe("deployment");
  });

  /**
   * 旧页面的「谁能进这个部署」和「共享文件夹」画在了同一块地方。
   *
   * 成因:页面根是一个**定了高度、会滚动**的 grid,注册那一节是一个带 `h-full min-h-0` 的
   * SettingsSectionStack,被当成这个 grid 的一行。`min-h-0` 让那一行的最小贡献变成 0 ——
   * 内容一超出视口,轨道就被压成 0 高,下一节从同一个 y 开始画。jsdom 不排版,所以这里守的是
   * 让这件事**在结构上不可能**的那几条:
   *   1. 页面根是 flex 列、子项一律 shrink-0(STUDIO_PAGE),不是 grid;
   *   2. 根以下没有任何元素带 h-full / min-h-0 —— 高度只由内容决定;
   *   3. 不再用 SettingsSectionStack(它自带 h-full min-h-0,是给「整个滚动区只有它」的设置页用的)。
   */
  it.each(["overview", "members", "deployment"] as const)("%s:没有哪一节能被压扁", async (tab) => {
    const { container } = show([admin, base], tab);
    await waitFor(() => expect(container.querySelector("[data-admin-section]")).not.toBeNull());
    const page = container.querySelector<HTMLElement>("[data-admin-page]")!;
    expect(page.className).toMatch(/\bflex-col\b/);
    expect(page.className).toContain("[&>*]:shrink-0");
    expect(page.className).not.toMatch(/(^|\s)grid(\s|$)/);

    const squeezable = [...page.querySelectorAll<HTMLElement>("*")].filter((el) =>
      /(^|\s)(h-full|min-h-0)(\s|$)/.test(el.getAttribute("class") ?? ""),
    );
    expect(squeezable.map((el) => el.outerHTML.slice(0, 80))).toEqual([]);
    expect(page.querySelector("[data-slot=settings-section-stack]")).toBeNull();

    // 节与节是兄弟,不互相嵌套 —— 嵌进去的那一节会跟着外面那一节的高度走。
    for (const section of page.querySelectorAll("[data-admin-section]")) {
      expect(section.parentElement?.closest("[data-admin-section]")).toBeNull();
    }
  });
});

describe("概览", () => {
  it("范围只有一个控件,换了它两张图跟着重取,标题里写着范围", async () => {
    show();
    await screen.findByText("adminStatUsers");
    expect(calls.overview).toHaveBeenLastCalledWith(30);
    expect(screen.getAllByText(/statLastNDays/)).toHaveLength(3);

    const range = screen.getByRole("radiogroup", { name: "statRangeLabel" });
    fireEvent.click(within(range).getAllByRole("radio")[0]);
    await waitFor(() => expect(calls.overview).toHaveBeenLastCalledWith(7));
    expect(within(range).getAllByRole("radio")[0]).toHaveAttribute("aria-checked", "true");
    expect(localStorage.getItem("mosael:tab:admin-range")).toBe("7");
  });

  // 人民币和美元**不相加**:每个人各币种各写一笔;条形按主要币种(costs 第一笔)量。
  it("按人分的花费每个币种各写一笔,条形只按主要币种量", async () => {
    overview = {
      window_days: 30,
      jobs_by_day: [],
      costs: [{ currency: "CNY", micros: 32_000_000 }, { currency: "USD", micros: 4_500_000 }],
      spend_by_user: [
        { user_id: "u2", username: "mate", calls: 1, costs: [{ currency: "CNY", micros: 20_000_000 }] },
        {
          user_id: "u1",
          username: "demo",
          calls: 2,
          costs: [{ currency: "CNY", micros: 12_000_000 }, { currency: "USD", micros: 4_500_000 }],
        },
      ],
    };
    show();
    expect(await screen.findByText("CN¥12.00 + $4.50 · 2")).toBeInTheDocument();
    expect(screen.getByText("CN¥20.00 · 1")).toBeInTheDocument();
    expect(screen.queryByText(/16\.5/)).not.toBeInTheDocument();
    // 混着两种钱时,说清条形按哪种量、合计是多少(各币种一笔)。
    expect(screen.getByText("adminSpendCurrencyHint")).toBeInTheDocument();
  });

  it("没有花费时给下一步:去设置价格规则", async () => {
    const { gotoSettings } = await import("@/lib/deepLink");
    show();
    fireEvent.click(await screen.findByRole("button", { name: "homeChartUsageConfigurePricing" }));
    expect(gotoSettings).toHaveBeenCalledWith("provider-pricing");
  });
});

describe("成员", () => {
  /**
   * 管理页那一栏曾写着「**vbrowser-extension**」:`X-Mosael-Client` 在桌面端发版本号,在浏览器
   * 扩展发字面量 `browser-extension`,后端原样存、这里照着渲染 `v{...}`。
   */
  it("扩展的会话显示「浏览器扩展 v<版本>」,而不是把产品名当版本号", async () => {
    show([{ ...base, client_surface: "browser-extension", client_version: "0.1.0" }], "members");
    expect(await screen.findByText("adminSurfaceExtension v0.1.0")).toBeInTheDocument();
    expect(screen.queryByText(/vbrowser-extension/)).not.toBeInTheDocument();
  });

  it("桌面端不加前缀 —— 每一行都写一遍「桌面端」等于什么都没说", async () => {
    show([{ ...base, client_surface: "app", client_version: "1.4.3" }], "members");
    expect(await screen.findByText("v1.4.3")).toBeInTheDocument();
  });

  it("老客户端报不上来时说「未知」,不编一个号", async () => {
    show([{ ...base, client_surface: "", client_version: "" }], "members");
    expect(await screen.findByText("adminUnknownVersion")).toBeInTheDocument();
  });

  it("授予部署管理员、删除账号都从这一行的菜单里走,删除先问一句", async () => {
    show([admin, base], "members");
    const row = (await screen.findByText("Demo")).closest("tr")!;

    fireEvent.click(within(row).getByRole("button", { name: /adminRowActions/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /adminGrantAdmin/ }));
    await waitFor(() => expect(calls.setAdmin).toHaveBeenCalledWith("u1", true));

    fireEvent.click(within(row).getByRole("button", { name: /adminRowActions/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /adminDeleteUser/ }));
    expect(calls.deleteAccount).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "confirm" }));
    await waitFor(() => expect(calls.deleteAccount).toHaveBeenCalledWith("u1"));
  });

  it("最后一位部署管理员收不回、也删不得(后端会 409,这里先不给点)", async () => {
    show([admin, base], "members");
    const row = (await screen.findByText("Boss")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: /adminRowActions/ }));
    expect(await screen.findByRole("menuitem", { name: /adminRevokeAdmin/ })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: /adminDeleteUser/ })).toBeDisabled();
  });

  it("开放注册时不摆发码按钮,只说一句并给去改的路", async () => {
    show([admin], "members");
    expect(await screen.findByText("adminInvitesOpenNote")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /deployInviteNew/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "adminInvitesOpenAction" }));
    expect(await screen.findByRole("switch", { name: "deployRegistrationOpen" })).toBeInTheDocument();
  });

  it("仅限邀请时列出邀请码(备注按行内 markdown 渲染),生成走弹窗", async () => {
    openRegistration = false;
    show([admin], "members");
    expect(await screen.findByText("CODE1")).toBeInTheDocument();
    expect(screen.getByText("Sam").tagName).toBe("STRONG");

    fireEvent.click(screen.getByRole("button", { name: /deployInviteNew/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/deployInviteNoteLabel/), { target: { value: "for Kim" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "deployInviteCreate" }));
    await waitFor(() => expect(calls.createInvite).toHaveBeenCalledWith("for Kim"));
  });
});

describe("部署设置", () => {
  it("注册开关直接改后端,不用改环境变量重启", async () => {
    show([admin], "deployment");
    const toggle = await screen.findByRole("switch", { name: "deployRegistrationOpen" });
    await waitFor(() => expect(toggle).toBeChecked());
    fireEvent.click(toggle);
    await waitFor(() => expect(calls.setOpenRegistration).toHaveBeenCalledWith(false));
    await waitFor(() => expect(screen.getByText("deployRegistrationOpenOff")).toBeInTheDocument());
  });
});
