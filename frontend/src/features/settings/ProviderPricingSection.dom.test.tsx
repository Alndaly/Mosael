/** @vitest-environment jsdom */
/**
 * 设置 → AI 成本规则。钉住三件被用户撞到的事:
 * - 「按目录预填」只转点的那一行(此前整列一起转圈变灰),结果说清是哪一家;
 * - 删一条规则要确认(此前一点就没,而批量删却有确认框);
 * - 编辑表单里只有字段标题加粗(此前整个 label 带 font-semibold,输入框里的字全成了粗体)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const { ProviderPricingSection } = await import("./ProviderPricingSection");

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
const PROFILES = [
  { id: "p1", name: "DeepSeek", vendor: "deepseek", capability_ids: ["chat"] },
  { id: "p2", name: "百炼qwen", vendor: "dashscope", capability_ids: ["image"] },
];
const RULE = {
  id: "r1", workspace_id: "ws", provider_profile_id: "p1", provider: "deepseek", capability: "chat", model: "deepseek-v4-pro",
  billing_unit: "input_1m_tokens", unit_amount_micros: 435000, currency: "USD", source: "manual", notes: "",
};

const PEAK = [
  { start: "09:00", end: "12:00", weekdays: [1, 2, 3, 4, 5], unit_amount_micros: 870000 },
  { start: "14:00", end: "18:00", weekdays: [1, 2, 3, 4, 5], unit_amount_micros: 870000 },
];
const TIMED_RULE = { ...RULE, id: "r2", model: "deepseek-flash", time_prices: PEAK, time_zone: "Asia/Shanghai" };

const outcome = (patch: Record<string, unknown>) => ({
  created: 0,
  created_from_catalog: 0,
  created_from_reference: 0,
  created_with_time_prices: 0,
  models_seen: 0,
  models_with_price: 0,
  unpriced_models: [],
  ...patch,
});

const originalFetch = globalThis.fetch;
afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
});

const sent: Array<{ method: string; url: string; body: Record<string, unknown> }> = [];

function mount(onPrefill?: (resolve: (r: Response) => void) => void, rules: unknown[] = [RULE]) {
  const calls: string[] = [];
  sent.length = 0;
  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (init?.method === "POST" || init?.method === "PATCH") {
      if (url.includes("/provider-pricing-rules")) {
        sent.push({ method: init.method, url, body: JSON.parse(String(init.body)) });
        return Promise.resolve(json(RULE));
      }
    }
    if (url.includes("/pricing/prefill")) return new Promise<Response>((resolve) => onPrefill?.(resolve));
    if (url.includes("/api/settings/providers")) return Promise.resolve(json(PROFILES));
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    if (url.includes("/provider-pricing-rules")) return Promise.resolve(json(rules));
    return Promise.resolve(json([]));
  }) as typeof fetch;
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ProviderPricingSection workspace={{ id: "ws" } as never} />
    </QueryClientProvider>,
  );
  return calls;
}

it("按目录预填只转点的那一行,其余只是按不动;结果带上是哪一家", async () => {
  let finish: (r: Response) => void = () => {};
  mount((resolve) => { finish = resolve; });
  fireEvent.click(await screen.findByRole("button", { name: /pricingPrefill/ }));
  const deepseek = await screen.findByRole("button", { name: "pricingPrefillOne: DeepSeek" });
  const qwen = screen.getByRole("button", { name: "pricingPrefillOne: 百炼qwen" });
  fireEvent.click(deepseek);
  await waitFor(() => expect(deepseek).toHaveAttribute("aria-busy", "true"));
  expect(qwen).not.toHaveAttribute("aria-busy", "true");
  expect(qwen).toBeDisabled();

  finish(json(outcome({ models_seen: 4, models_with_price: 3, unpriced_models: ["deepseek-chat"] })));
  // 结果写在**这一家自己那一行**底下,不是另起一块堆在最下面。
  const row = deepseek.closest("li")!;
  await waitFor(() => expect(within(row).getByText("pricingPrefillUnpriced")).toBeTruthy());
  expect(qwen).not.toBeDisabled();
  expect(within(qwen.closest("li")!).queryByText("pricingPrefillUnpriced")).toBeNull();
  expect(deepseek).toHaveAccessibleName("pricingPrefillAgain: DeepSeek");
});

it("全部预填挨个跑:一次只转一行,每家的结果各记一条,一家失败不打断其余几家", async () => {
  const pending: Array<{ url: string; resolve: (r: Response) => void }> = [];
  const calls = mount((resolve) => pending.push({ url: "", resolve }));
  fireEvent.click(await screen.findByRole("button", { name: /pricingPrefill$/ }));
  const deepseek = await screen.findByRole("button", { name: "pricingPrefillOne: DeepSeek" });
  const qwen = screen.getByRole("button", { name: "pricingPrefillOne: 百炼qwen" });
  fireEvent.click(screen.getByRole("button", { name: /pricingPrefillAll/ }));

  await waitFor(() => expect(deepseek).toHaveAttribute("aria-busy", "true"));
  expect(qwen).not.toHaveAttribute("aria-busy", "true");
  expect(calls.filter((c) => c.includes("/pricing/prefill"))).toHaveLength(1);

  pending[0].resolve(new Response(JSON.stringify({ detail: "no key" }), { status: 422, headers: { "content-type": "application/json" } }));
  await waitFor(() => expect(qwen).toHaveAttribute("aria-busy", "true"));
  const prefillCalls = calls.filter((c) => c.includes("/pricing/prefill"));
  expect(prefillCalls).toHaveLength(2);
  expect(prefillCalls[0]).toMatch(/^POST .*\/providers\/p1\/pricing\/prefill$/);
  expect(prefillCalls[1]).toMatch(/^POST .*\/providers\/p2\/pricing\/prefill$/);

  pending[1].resolve(json(outcome({ created: 3, created_from_reference: 3, models_seen: 3, models_with_price: 3 })));
  await waitFor(() => expect(within(qwen.closest("li")!).getByText("pricingPrefillDone")).toBeTruthy());
  expect(within(deepseek.closest("li")!).getByText("no key")).toBeTruthy();
  expect(within(qwen.closest("li")!).getByText("pricingPrefillAllPriced")).toBeTruthy();
});

it("删一条规则先确认,确认了才发 DELETE", async () => {
  const calls = mount();
  await screen.findByText(/deepseek-v4-pro/);
  fireEvent.click(screen.getByRole("button", { name: /^delete: / }));
  expect(await screen.findByText("pricingRuleDeleteTitle")).toBeTruthy();
  expect(calls.some((c) => c.startsWith("DELETE"))).toBe(false);
  const dialog = screen.getByRole("alertdialog");
  fireEvent.click(Array.from(dialog.querySelectorAll("button")).find((b) => b.textContent === "delete")!);
  await waitFor(() => expect(calls.some((c) => c.startsWith("DELETE") && c.endsWith("/api/settings/provider-pricing-rules/r1"))).toBe(true));
});

it("编辑表单里只有字段标题加粗,控件本身不继承粗体", async () => {
  mount();
  await screen.findByText(/deepseek-v4-pro/);
  fireEvent.click(screen.getAllByRole("button", { name: /^pricingRuleEdit: / })[0]);
  const model = await screen.findByDisplayValue("deepseek-v4-pro");
  const field = model.closest("label")!;
  expect(field.className).not.toMatch(/font-semibold|font-bold/);
  expect(field.querySelector("span")!.textContent).toBe("pricingModel");
});

/** 逐个点「移除」:每点一下列表就重排,手里攥着的旧按钮已经不在文档里了。 */
function removeAllWindows() {
  for (let left = screen.queryAllByRole("button", { name: "pricingTimeWindowRemove" }); left.length; ) {
    fireEvent.click(left[0]);
    left = screen.queryAllByRole("button", { name: "pricingTimeWindowRemove" });
  }
}

it("列表行把分时段价格压成一句:同星期同价的时段并在一起,时区说人话", async () => {
  mount(undefined, [TIMED_RULE]);
  await screen.findByText(/deepseek-flash/);
  expect(screen.getByText(/pricingWorkdays/).textContent).toContain("pricingWorkdays 09:00–12:00, 14:00–18:00 0.87 (pricingZoneBeijing)");
});

it("编辑:删光时段再加一段,时区预选这家已有规则的时区;点掉周末,提交的就是工作日", async () => {
  mount(undefined, [TIMED_RULE]);
  await screen.findByText(/deepseek-flash/);
  fireEvent.click(screen.getAllByRole("button", { name: /^pricingRuleEdit: / })[0]);
  await waitFor(() => expect(screen.getAllByTestId("pricing-time-window")).toHaveLength(2));
  expect(screen.getAllByRole("button", { name: "pricingTimeWindowStart" }).map((b) => b.textContent)).toEqual(["09:00", "14:00"]);

  removeAllWindows();
  expect(screen.queryAllByTestId("pricing-time-window")).toHaveLength(0);
  expect(screen.queryByRole("button", { name: "pricingTimeZone" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: /pricingTimeWindowAdd/ }));
  const [window] = screen.getAllByTestId("pricing-time-window");
  const days = within(window).getByRole("group", { name: "pricingTimeWindowDays" });
  const [saturday, sunday] = within(days).getAllByRole("button").slice(5);
  fireEvent.click(saturday);
  fireEvent.click(sunday);
  expect(saturday).toHaveAttribute("aria-pressed", "false");
  fireEvent.change(within(window).getByLabelText("pricingTimeWindowAmount"), { target: { value: "0.5" } });

  fireEvent.click(screen.getByRole("button", { name: "save" }));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0].method).toBe("PATCH");
  expect(sent[0].body.time_prices).toEqual([{ start: "09:00", end: "18:00", weekdays: [1, 2, 3, 4, 5], unit_amount_micros: 500000 }]);
  expect(sent[0].body.time_zone).toBe("Asia/Shanghai");
});

it("点掉最后一个星期不生效(后端把「一天都不选」读作每天);加两段删一段,没有时段就不带时区", async () => {
  mount();
  await screen.findByText(/deepseek-v4-pro/);
  fireEvent.click(screen.getAllByRole("button", { name: /pricingRuleAdd/ })[0]);
  fireEvent.change(await screen.findByPlaceholderText("0.000000"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: /pricingTimeWindowAdd/ }));
  fireEvent.click(screen.getByRole("button", { name: /pricingTimeWindowAdd/ }));
  const windows = screen.getAllByTestId("pricing-time-window");
  expect(windows).toHaveLength(2);
  // 第二段接在第一段后面,单价先照抄基础价。
  expect(within(windows[1]).getByRole("button", { name: "pricingTimeWindowStart" }).textContent).toContain("18:00");
  expect(within(windows[1]).getByLabelText("pricingTimeWindowAmount")).toHaveValue(2);

  const buttons = within(within(windows[0]).getByRole("group")).getAllByRole("button");
  for (const day of buttons) fireEvent.click(day);
  expect(buttons.filter((b) => b.getAttribute("aria-pressed") === "true")).toHaveLength(1);

  removeAllWindows();
  fireEvent.click(screen.getAllByRole("button", { name: /pricingRuleAdd/ }).at(-1)!);
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0].body).toMatchObject({ unit_amount_micros: 2_000_000, time_prices: [], time_zone: "" });
});

it("预填结果里单独说一句有几条带分时段价格", async () => {
  let finish: (r: Response) => void = () => {};
  mount((resolve) => { finish = resolve; });
  fireEvent.click(await screen.findByRole("button", { name: /pricingPrefill$/ }));
  const deepseek = await screen.findByRole("button", { name: "pricingPrefillOne: DeepSeek" });
  fireEvent.click(deepseek);
  await waitFor(() => expect(deepseek).toHaveAttribute("aria-busy", "true"));
  finish(json(outcome({ created: 6, created_from_reference: 6, created_with_time_prices: 6, models_seen: 2, models_with_price: 2 })));
  expect(await screen.findByText("pricingPrefillTimed")).toBeTruthy();
});

// —— 浏览:按模型成组、筛选搜索、卡片 / 列表 ——
const INPUT = { ...RULE, id: "g1", model: "qwen-flash", provider_profile_id: "p2", provider: "dashscope", billing_unit: "million_input_token", unit_amount_micros: 150000, currency: "CNY", source: "reference", notes: "官方价目(中国内地)" };
const OUTPUT = { ...INPUT, id: "g2", billing_unit: "million_output_token", unit_amount_micros: 1500000 };
const OTHER = { ...RULE, id: "g3", model: "deepseek-v4-pro", billing_unit: "million_input_token", source: "manual" };

it("同一连接、同一模型的几条价格收成一张卡片,各条仍能单独改删", async () => {
  mount(undefined, [INPUT, OUTPUT, OTHER]);
  const title = await screen.findByText("qwen-flash");
  const card = title.closest("article")!;
  expect(within(card).getByText("0.15 CNY")).toBeTruthy();
  expect(within(card).getByText("1.5 CNY")).toBeTruthy();
  expect(within(card).getAllByRole("button", { name: /^pricingRuleEdit: / })).toHaveLength(2);
  expect(within(card).getByText("pricingSource_reference")).toBeTruthy();
  expect(screen.getAllByRole("article")).toHaveLength(2); // 三条规则,两个模型
  expect(screen.getByText(/pricingCount/)).toBeTruthy();
});

it("搜索和按来源筛选;筛完没有东西时说清楚,并能一键清掉", async () => {
  mount(undefined, [INPUT, OUTPUT, OTHER]);
  await screen.findByText("qwen-flash");
  fireEvent.change(screen.getByRole("textbox", { name: "pricingSearch" }), { target: { value: "deepseek" } });
  expect(screen.queryByText("qwen-flash")).toBeNull();
  expect(screen.getByText("deepseek-v4-pro")).toBeTruthy();

  fireEvent.change(screen.getByRole("textbox", { name: "pricingSearch" }), { target: { value: "没有这个模型" } });
  expect(screen.getByText("pricingNoMatch")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "pricingClearFilters" }));
  expect(screen.getAllByRole("article")).toHaveLength(2);
});

it("卡片 / 列表可以切,选择记住到下次", async () => {
  localStorage.clear();
  mount(undefined, [INPUT, OUTPUT, OTHER]);
  await screen.findByText("qwen-flash");
  expect(screen.getAllByRole("article")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "studioListView" }));
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  expect(screen.getByRole("button", { name: "studioListView" })).toHaveAttribute("aria-pressed", "true");
  cleanup();
  mount(undefined, [INPUT, OUTPUT, OTHER]);
  await screen.findByText("qwen-flash");
  expect(screen.queryAllByRole("article")).toHaveLength(0);
  localStorage.clear();
});

it("删一个模型的全部价格:确认后逐条删掉这一组", async () => {
  const calls = mount(undefined, [INPUT, OUTPUT, OTHER]);
  await screen.findByText("qwen-flash");
  fireEvent.click(screen.getByRole("button", { name: "pricingDeleteGroup: qwen-flash" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText("pricingDeleteGroupTitle")).toBeTruthy();
  fireEvent.click(Array.from(dialog.querySelectorAll("button")).find((b) => b.textContent === "delete")!);
  await waitFor(() => {
    const deletes = calls.filter((c) => c.startsWith("DELETE"));
    expect(deletes.map((c) => c.split("/").pop()).sort()).toEqual(["g1", "g2"]);
  });
});
