/** @vitest-environment jsdom */
/**
 * 设置 → AI 成本规则。钉住三件被用户撞到的事:
 * - 「按目录预填」只转点的那一行(此前整列一起转圈变灰),结果说清是哪一家;
 * - 删一条规则要确认(此前一点就没,而批量删却有确认框);
 * - 编辑表单里只有字段标题加粗(此前整个 label 带 font-semibold,输入框里的字全成了粗体)。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const originalFetch = globalThis.fetch;
afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
});

function mount(onPrefill?: (resolve: (r: Response) => void) => void) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (url.includes("/pricing/prefill")) return new Promise<Response>((resolve) => onPrefill?.(resolve));
    if (url.includes("/api/settings/providers")) return Promise.resolve(json(PROFILES));
    if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    if (url.includes("/provider-pricing-rules")) return Promise.resolve(json([RULE]));
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

  finish(json({ created: 0, models_seen: 4, models_with_price: 3 }));
  await screen.findByText("pricingPrefillResultFor");
  expect(qwen).not.toBeDisabled();
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
