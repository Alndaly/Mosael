/** @vitest-environment jsdom */
/**
 * 展开一条连接时的**加载态**。
 *
 * 用户撞到的:"初次加载会有 loading 模型的过程…现在甚至都没有居中"。原因不是没居中 ——
 * 那是一条左对齐的裸文字,既没有行高也没有内边距,贴在展开区边上;等真实行到了,整片再跳一下。
 *
 * 加载态要**占住它将要变成的那个版面**:同一套 SettingsList / SettingsListItem,同样的两列
 * 网格,右栏留出开关的宽度。这样内容到了是就地替换,不是重排。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
//: 让模型查询停在 pending —— 这一屏要测的就是"还没回来"的那一刻。
vi.mock("@/api/client", () => ({ api: () => new Promise(() => {}) }));

import { ProviderModelList } from "./ProviderModelList";

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProviderModelList profileId="p1" vendor="openai-compatible" />
    </QueryClientProvider>,
  );
}

it("加载态长在真实行的容器里,而不是一条贴边的文字", () => {
  mount();
  //: 拿 data-slot 找容器 —— 它是真实列表和占位共用的那一个,共用才谈得上"就地替换"。
  const container = document.querySelector('[data-slot="settings-list"]');
  expect(container).not.toBeNull();
  expect(container!.querySelectorAll('[data-slot="settings-list-item"]').length).toBeGreaterThan(0);
});

it("aria-busy 真的落到 DOM 上", () => {
  // TypeScript 对带连字符的 JSX 属性豁免多余属性检查 —— `<SettingsList aria-busy>` 曾经
  // 编译通过却被组件静默吃掉,读屏一无所知。写了等于没写,所以这条断言查的是 DOM 不是源码。
  mount();
  expect(document.querySelector('[data-slot="settings-list"]')).toHaveAttribute("aria-busy", "true");
});

it("占位行数固定,不冒充真实数量", () => {
  // 三行表示"正在来",不表示"有三个" —— 此刻真实数量还不知道。
  mount();
  expect(document.querySelectorAll('[data-slot="settings-list-item"]').length).toBe(3);
});
