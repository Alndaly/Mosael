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
  const deepseek = await screen.findByRole("button", { name: "DeepSeek" });
  const qwen = screen.getByRole("button", { name: "百炼qwen" });
  fireEvent.click(deepseek);
  await waitFor(() => expect(deepseek).toHaveAttribute("aria-busy", "true"));
  expect(qwen).not.toHaveAttribute("aria-busy", "true");
  expect(qwen).toBeDisabled();

  finish(json(outcome({ models_seen: 4, models_with_price: 3, unpriced_models: ["deepseek-chat"] })));
  await screen.findByText("pricingPrefillResultFor");
  expect(qwen).not.toBeDisabled();
  // 还剩哪些要手填,点名说出来 —— 那才是用户接下来要做的事。
  expect(screen.getByText("pricingPrefillUnpriced")).toBeTruthy();
});

it("全部预填挨个跑:一次只转一行,每家的结果各记一条,一家失败不打断其余几家", async () => {
  const pending: Array<{ url: string; resolve: (r: Response) => void }> = [];
  const calls = mount((resolve) => pending.push({ url: "", resolve }));
  fireEvent.click(await screen.findByRole("button", { name: /pricingPrefill$/ }));
  const deepseek = await screen.findByRole("button", { name: "DeepSeek" });
  const qwen = screen.getByRole("button", { name: "百炼qwen" });
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
  await waitFor(() => expect(screen.getAllByText("pricingPrefillResultFor")).toHaveLength(2));
  expect(screen.getByText("no key")).toBeTruthy();
  expect(screen.getByText("pricingPrefillDone")).toBeTruthy();
  expect(screen.getByText("pricingPrefillAllPriced")).toBeTruthy();
});

it("删一条规则先确认,确认了才发 DELETE", async () => {
  const calls = mount();
  await screen.findByText(/deepseek-v4-pro/);
  fireEvent.click(screen.getByRole("button", { name: "delete" }));
  expect(await screen.findByText("pricingRuleDeleteTitle")).toBeTruthy();
  expect(calls.some((c) => c.startsWith("DELETE"))).toBe(false);
  const dialog = screen.getByRole("alertdialog");
  fireEvent.click(Array.from(dialog.querySelectorAll("button")).find((b) => b.textContent === "delete")!);
  await waitFor(() => expect(calls.some((c) => c.startsWith("DELETE") && c.endsWith("/api/settings/provider-pricing-rules/r1"))).toBe(true));
});

it("编辑表单里只有字段标题加粗,控件本身不继承粗体", async () => {
  mount();
  await screen.findByText(/deepseek-v4-pro/);
  fireEvent.click(screen.getByRole("button", { name: "pricingRuleEdit" }));
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
  const row = await screen.findByText(/deepseek-flash/);
  expect(row.textContent).toContain("pricingWorkdays 09:00–12:00, 14:00–18:00 0.87 (pricingZoneBeijing)");
});

it("编辑:删光时段再加一段,时区预选这家已有规则的时区;点掉周末,提交的就是工作日", async () => {
  mount(undefined, [TIMED_RULE]);
  await screen.findByText(/deepseek-flash/);
  fireEvent.click(screen.getByRole("button", { name: "pricingRuleEdit" }));
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
  const deepseek = await screen.findByRole("button", { name: "DeepSeek" });
  fireEvent.click(deepseek);
  await waitFor(() => expect(deepseek).toHaveAttribute("aria-busy", "true"));
  finish(json(outcome({ created: 6, created_from_reference: 6, created_with_time_prices: 6, models_seen: 2, models_with_price: 2 })));
  expect(await screen.findByText("pricingPrefillTimed")).toBeTruthy();
});
