/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

/** 发布平台目录的说明和配置项说明来自后端,带 markdown 时按格式渲染。 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  listPublishPlatforms: async () => [
    {
      platform: "douyin",
      label: "抖音",
      description: "用**浏览器池**里的档案登录",
      config: { cookie_dir: { description: "留空用默认的 `profiles/` 目录", required: false } },
    },
  ],
}));

import { AddAccountDialog } from "@/features/publish/AddAccountDialog";

it("平台说明和配置项说明里的记号渲染成格式", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddAccountDialog open workspace={{ id: "w1" } as never} onClose={() => undefined} />
    </QueryClientProvider>,
  );
  expect((await screen.findByText("浏览器池")).tagName).toBe("STRONG");
  expect(screen.getByText("profiles/").tagName).toBe("CODE");
  expect(document.body.textContent).not.toMatch(/\*\*|`/);
});
