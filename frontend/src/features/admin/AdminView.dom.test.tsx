/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Workspace } from "@/api/client";

/**
 * 管理页:五个 tab 各自有哪几节、节与节**不可能叠在一起**、以及每一处会改东西的动作真的打到后端。
 *
 * 走真正的组件(只替掉接口和图表),不去测抽出来的字符串拼接函数:错常常发生在
 * "接口字段 → 屏幕上那行字"这一跳上,而那正是绕过组件就测不到的一跳。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("./AdminActivityChart", () => ({ AdminActivityChart: () => null }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
//: 登录着的是部署管理员 Boss(a1):他那一行的「重置密码」灰掉 —— 改自己的密码走「设置 → 账户」。
const viewer = vi.hoisted(() => ({ admin: true as boolean | undefined }));
vi.mock("@/app/auth", () => ({ useAuth: () => ({ user: { id: "a1" } }), useDeploymentAdmin: () => viewer.admin }));

const rows: Array<Record<string, unknown>> = [];
let overview: Record<string, unknown> = { spend_by_user: [], jobs_by_day: [], costs: [], window_days: 30 };
let overviewFails = false;
let openRegistration = true;
/** 出站代理读得到什么:null = 读失败(后端拒了、或者断网)。 */
let network: Record<string, unknown> | null = { proxy_url: "", no_proxy: "" };
const calls = {
  api: vi.fn(),
  overview: vi.fn(),
  setAdmin: vi.fn(),
  deleteAccount: vi.fn(),
  resetPassword: vi.fn(),
  setOpenRegistration: vi.fn(),
  createInvite: vi.fn(),
  revokeInvite: vi.fn(),
};
/** 部署设置与成本规则那几节走通用的 `api(path)`:按路径给一份最小的回包。 */
function fakeApi(path: string, init?: RequestInit): Promise<unknown> {
  calls.api(init?.method ?? "GET", path, init?.body ? JSON.parse(String(init.body)) : undefined);
  if (path === "/api/settings/network") {
    if (init?.method === "PUT") return Promise.resolve(JSON.parse(String(init.body)));
    return network ? Promise.resolve(network) : Promise.reject(new Error("forbidden"));
  }
  if (path === "/api/settings/ai-runtime") return Promise.resolve({ max_retries: 3 });
  return Promise.resolve([]);
}
//: 裸路径和 api/domains/providers 的函数都经 transport 的 api;管理页自己那几个函数在 client 上单独替掉。
vi.mock("@/api/transport", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/transport")>()),
  api: (path: string, init?: RequestInit) => fakeApi(path, init),
}));
vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  getAuthToken: () => "token",
  isCustomServer: () => false,
  getInstallSource: () => Promise.resolve({ pip_index: "" }),
  updateInstallSource: (body: { pip_index?: string }) => Promise.resolve({ pip_index: body.pip_index ?? "" }),
  adminOverview: (days: number) => {
    calls.overview(days);
    return overviewFails ? Promise.reject(new Error("boom")) : Promise.resolve({ ...overview, window_days: days });
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
  resetUserPassword: (id: string) => {
    calls.resetPassword(id);
    return Promise.resolve({ password: "Temp-Pass-123" });
  },
  authBootstrap: () => Promise.resolve({ has_users: true, open_registration: openRegistration }),
  setOpenRegistration: (open: boolean) => {
    calls.setOpenRegistration(open);
    openRegistration = open;
    return Promise.resolve({ open });
  },
  registrationInvites: () => Promise.resolve([{ code: "CODE1", note: "for **Sam**", used: false, expires_at: "2099-01-01T00:00:00Z" }]),
  revokeRegistrationInvite: (code: string) => {
    calls.revokeInvite(code);
    return Promise.resolve();
  },
  createRegistrationInvite: (note: string) => {
    calls.createInvite(note);
    return Promise.resolve({ code: "NEW", note, used: false, expires_at: "2099-01-01T00:00:00Z" });
  },
  getSharedHostFolders: () => Promise.resolve({ folders: [] }),
  getOutboundAllowlist: () => Promise.resolve({ entries: [] }),
  setOutboundAllowlist: (entries: string[]) => Promise.resolve({ entries }),
  // 引擎 tab:几节各自的清单。结构测试只关心有哪几节,给空清单就够。
  listAsrModels: () => Promise.resolve([]),
  downloadAsrModel: () => Promise.resolve({}),
  getTtsConfig: () => Promise.resolve({ engine: "f5-tts", python_path: "", source: "hf", worker_ready: true, worker_python: "" }),
  updateTtsConfig: () => Promise.resolve({}),
  listTtsModels: () => Promise.resolve([]),
  downloadTtsModel: () => Promise.resolve({}),
  listSeparationEngines: () => Promise.resolve([]),
  installSeparationEngine: () => Promise.resolve({}),
  listDenoiseEngines: () => Promise.resolve([]),
  installDenoiseEngine: () => Promise.resolve({}),
  setSharedHostFolders: (folders: string[]) => Promise.resolve({ folders }),
}));

const { AdminView } = await import("./AdminView");

function show(people: Array<Record<string, unknown>> = [], tab?: "overview" | "members" | "pricing" | "engines" | "deployment") {
  rows.length = 0;
  rows.push(...people);
  if (tab) localStorage.setItem("mosael:tab:admin", tab);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminView workspace={{ id: "ws", name: "Studio" } as Workspace} />
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
  network = { proxy_url: "", no_proxy: "" };
  overview = { spend_by_user: [], jobs_by_day: [], costs: [], window_days: 30 };
  overviewFails = false;
  viewer.admin = true;
  for (const fn of Object.values(calls)) fn.mockClear();
});

/** 页面上画出来的节,按出现顺序。 */
function sections(container: HTMLElement) {
  return [...container.querySelectorAll<HTMLElement>("[data-admin-section]")].map((el) => el.dataset.adminSection);
}

describe("结构", () => {
  it("五个 tab 各有自己的几节,切换只换内容区", async () => {
    const { container } = show([admin, base]);
    await screen.findByText("adminStatUsers");
    expect(sections(container)).toEqual(["range", "stats", "activity", "spend"]);

    fireEvent.click(screen.getByRole("button", { name: "adminTabMembers" }));
    await screen.findByText("Demo");
    expect(sections(container)).toEqual(["accounts", "invites"]);

    fireEvent.click(screen.getByRole("button", { name: "adminTabPricing" }));
    await screen.findByText("pricingRulesTitle");
    expect(sections(container)).toEqual(["pricing"]);

    // 本机引擎的安装与下载源:后端只许部署管理员装(ensure_deployment_admin),所以在这里、不在设置页。
    // 下载源排在最前 —— 它只管装这几个引擎的依赖,先选好从哪儿拉,再点下面的安装。
    fireEvent.click(screen.getByRole("button", { name: "adminTabEngines" }));
    await screen.findByText("asrModelsTitle");
    expect(sections(container)).toEqual([
      "install-source",
      "engine-transcribe",
      "engine-clone",
      "engine-separation",
      "engine-denoise",
    ]);

    // 只有部署管理员写得了的设置都在这里,不在设置页(见 AdminView 的说明)。
    fireEvent.click(screen.getByRole("button", { name: "adminTabDeployment" }));
    await screen.findByRole("switch", { name: "deployRegistrationOpen" });
    expect(sections(container)).toEqual(["registration", "shared-folders", "outbound-allowlist", "proxy", "ai-runtime", "data", "storage"]);
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
  it.each(["overview", "members", "pricing", "engines", "deployment"] as const)("%s:没有哪一节能被压扁", async (tab) => {
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

  //: 体检 UM-11 的过渡修法:不挂任务的用量列在最后一行「无归属」,各行加起来等于合计,并说清它是什么。
  it("没记下是谁花的那部分列成「无归属」,条形淡一些,下面说清是哪些", async () => {
    overview = {
      window_days: 30,
      jobs_by_day: [],
      costs: [{ currency: "USD", micros: 8_000_000 }],
      spend_by_user: [
        { user_id: "u1", username: "demo", calls: 1, costs: [{ currency: "USD", micros: 1_000_000 }] },
        { user_id: "", username: "", calls: 2, costs: [{ currency: "USD", micros: 7_000_000 }] },
      ],
    };
    const { container } = show();
    expect(await screen.findByText("adminNoOwner")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-spend-unattributed]")).toHaveLength(1);
    expect(screen.getByText("adminSpendUnattributedHint")).toBeInTheDocument();
  });

  //: 体检 UM-21:取不回来时此前四个读数是「—」、「谁在花钱」写「还没有产生花费」+「去设置价格规则」。
  it("概览取不回来:说取不回来、能重试,不画成「还没有产生花费」", async () => {
    overviewFails = true;
    show();
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByText("adminNoSpendTitle")).toBeNull();
    expect(screen.queryByText("adminStatUsers")).toBeNull();
  });

  it("不是部署管理员的人打开管理页:直接说这一页是谁的,不发那几个会 403 的请求", async () => {
    viewer.admin = false;
    const { container } = show();
    expect(screen.getByText("adminOnlyTitle")).toBeInTheDocument();
    expect(container.querySelector("[data-admin-forbidden]")).not.toBeNull();
    expect(screen.queryByRole("group", { name: "adminTabsLabel" })).toBeNull();
    expect(calls.overview).not.toHaveBeenCalled();
  });

  it("没有花费时给下一步:同一页的「成本规则」tab,不跳去设置页", async () => {
    const { container } = show();
    fireEvent.click(await screen.findByRole("button", { name: "homeChartUsageConfigurePricing" }));
    await screen.findByText("pricingRulesTitle");
    expect(sections(container)).toEqual(["pricing"]);
    expect(localStorage.getItem("mosael:tab:admin")).toBe("pricing");
  });

  it("统计页的「N 次未定价」经深链落到成本规则 tab", async () => {
    const { gotoAdmin } = await import("@/lib/deepLink");
    const { container } = show();
    await screen.findByText("adminStatUsers");
    act(() => gotoAdmin("pricing"));
    await screen.findByText("pricingRulesTitle");
    expect(sections(container)).toEqual(["pricing"]);
    // 认不出的 tab 原地不动。
    act(() => gotoAdmin("没有这个"));
    expect(sections(container)).toEqual(["pricing"]);
  });

  it("转写、降噪、配音处「引擎没装」的「去安装」经深链落到引擎 tab", async () => {
    const { gotoAdmin } = await import("@/lib/deepLink");
    const { container } = show();
    await screen.findByText("adminStatUsers");
    act(() => gotoAdmin("engines"));
    await screen.findByText("asrModelsTitle");
    expect(sections(container)).toContain("engine-transcribe");
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

  it("忘了密码的成员从他那一行的菜单里重置:先问一句,临时密码只在弹窗里给一次;自己那一行不给点", async () => {
    show([admin, base], "members");
    const row = (await screen.findByText("Demo")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: /adminRowActions/ }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /adminResetPassword/ }));
    expect(calls.resetPassword).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("alertdialog");
    expect(confirm.textContent).toContain("adminResetPasswordBody");
    fireEvent.click(within(confirm).getByRole("button", { name: "adminResetPassword" }));
    await waitFor(() => expect(calls.resetPassword).toHaveBeenCalledWith("u1"));
    expect((await screen.findByText("Temp-Pass-123")).closest("[data-temporary-password]")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "close" }));

    const mine = (await screen.findByText("Boss")).closest("tr")!;
    fireEvent.click(within(mine).getByRole("button", { name: /adminRowActions/ }));
    expect(await screen.findByRole("menuitem", { name: /adminResetPassword/ })).toBeDisabled();
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

  //: 体检 UM-09:发出去的码此前撤不回,只能等它 7 天后过期。
  it("没用过的邀请码能作废(先问一句)", async () => {
    openRegistration = false;
    show([admin], "members");
    fireEvent.click(await screen.findByRole("button", { name: "deployInviteRevoke" }));
    expect(calls.revokeInvite).not.toHaveBeenCalled();
    const confirm = await screen.findByRole("alertdialog");
    fireEvent.click(within(confirm).getByRole("button", { name: "deployInviteRevoke" }));
    await waitFor(() => expect(calls.revokeInvite).toHaveBeenCalledWith("CODE1"));
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

  /**
   * 代理读不到时**不给填**。设置页那一版读被拒后照样画两个空框 —— 读起来就是「直连」,一句错话;
   * 顺手一存还会把真正的代理清掉。
   */
  it("出站代理没读到就不给填;读到了才能改、存", async () => {
    network = null;
    show([admin], "deployment");
    const url = await screen.findByRole("textbox", { name: "proxyUrl" });
    await waitFor(() => expect(calls.api).toHaveBeenCalledWith("GET", "/api/settings/network", undefined));
    expect(url).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "proxyNoProxy" })).toBeDisabled();
  });

  it("出站代理改完才能存,存的是逗号分隔的绕过列表", async () => {
    network = { proxy_url: "", no_proxy: "a.com, b.com" };
    show([admin], "deployment");
    const url = await screen.findByRole("textbox", { name: "proxyUrl" });
    await waitFor(() => expect(url).toBeEnabled());
    const save = within(screen.getByRole("region", { name: "proxyTitle" })).getByRole("button", { name: "save" });
    expect(save).toBeDisabled();
    fireEvent.change(url, { target: { value: "http://127.0.0.1:7890" } });
    fireEvent.click(save);
    await waitFor(() =>
      expect(calls.api).toHaveBeenCalledWith("PUT", "/api/settings/network", { proxy_url: "http://127.0.0.1:7890", no_proxy: "a.com, b.com" }),
    );
  });
});
