/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

/**
 * 管理页那一栏此前写着「**vbrowser-extension**」。
 *
 * `X-Mosael-Client` 在两个客户端上是两个意思:桌面端发版本号,浏览器扩展发字面量
 * `browser-extension`。后端原样存进 `auth_sessions.client_version`,这里照着渲染 `v{...}`。
 * 两边各自都"对",错在这一栏从来没有被定义过是什么 —— 而**没有任何一处测试看过这个字符串**,
 * 所以它一直那么显示着。
 *
 * 这条测试走真正的组件,不去测一个抽出来的字符串拼接函数:错发生在"接口字段 → 屏幕上那行字"
 * 这一跳上,而那正是绕过组件就测不到的一跳。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t, usePreferences: () => ({ locale: "en-US" }) }));
vi.mock("./AdminActivityChart", () => ({ AdminActivityChart: () => null }));
vi.mock("./RegistrationSection", () => ({ RegistrationSection: () => null }));
vi.mock("./SharedHostFoldersSection", () => ({ SharedHostFoldersSection: () => null }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const rows: Array<Record<string, unknown>> = [];
let overview: Record<string, unknown> = { spend_by_user: [], activity: [] };
vi.mock("@/api/client", () => ({
  api: (path: string) => {
    if (path === "/api/admin/users") return Promise.resolve(rows);
    return Promise.resolve(overview);
  },
}));

const { AdminView } = await import("./AdminView");

function show(people: Array<Record<string, unknown>>) {
  rows.length = 0;
  rows.push(...people);
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
};

it("扩展的会话显示「浏览器扩展 v<版本>」,而不是把产品名当版本号", async () => {
  show([{ ...base, client_surface: "browser-extension", client_version: "0.1.0" }]);

  expect(await screen.findByText("adminSurfaceExtension v0.1.0")).toBeInTheDocument();
  expect(screen.queryByText(/vbrowser-extension/)).not.toBeInTheDocument();
});

it("桌面端不加前缀 —— 每一行都写一遍「桌面端」等于什么都没说", async () => {
  show([{ ...base, client_surface: "app", client_version: "1.4.3" }]);

  expect(await screen.findByText("v1.4.3")).toBeInTheDocument();
});

it("老客户端报不上来时说「未知」,不编一个号", async () => {
  show([{ ...base, client_surface: "", client_version: "" }]);

  expect(await screen.findByText("adminUnknownVersion")).toBeInTheDocument();
});


// 人民币和美元**不相加**:每个人各币种各写一笔;条形按主要币种(costs 第一笔)量。
it("按人分的花费每个币种各写一笔,条形只按主要币种量", async () => {
  overview = {
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
  show([]);
  expect(await screen.findByText("CN¥12.00 + $4.50 · 2")).toBeInTheDocument();
  expect(screen.getByText("CN¥20.00 · 1")).toBeInTheDocument();
  expect(screen.queryByText(/16\.5/)).not.toBeInTheDocument();
  // 混着两种钱时,说清条形按哪种量、合计是多少(各币种一笔)。
  expect(screen.getByText("adminSpendCurrencyHint")).toBeInTheDocument();
  overview = { spend_by_user: [], activity: [] };
});
