/** @vitest-environment jsdom */
/**
 * 体检 UM-23:缺密钥的连接旁边亮着绿色的「275ms」,读起来像「连上了」。地址通而我用不了时,圆点不用成功色。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", () => ({
  probeProviderHealth: async () => ({ supported: true, online: true, latency_ms: 275, detail: "" }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { ProviderHealth } from "./ProviderHealth";

function show(usable: boolean) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TooltipProvider>
        <ProviderHealth profileId="p1" usable={usable} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

it("地址通、能用:成功色;地址通、我用不了:不亮成功色", async () => {
  const usable = show(true);
  await waitFor(() => expect(usable.container.querySelector('[data-health-dot="online"]')).not.toBeNull());
  expect(usable.container.querySelector("[data-health-dot]")?.className).toContain("bg-success");
  usable.unmount();

  const blocked = show(false);
  await waitFor(() => expect(blocked.container.querySelector('[data-health-dot="reachable"]')).not.toBeNull());
  expect(blocked.container.querySelector("[data-health-dot]")?.className).not.toContain("bg-success");
  expect(blocked.container.textContent).toContain("275ms");
});
