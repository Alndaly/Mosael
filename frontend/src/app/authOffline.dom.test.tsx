/** @vitest-environment jsdom */
/**
 * 「连不上」和「服务端说不行」必须分开处理,而它们混在一起时**没有任何东西会报错**:
 *
 *  · 后端一时没起来(本机进程,重启、休眠唤醒、启动时抢跑都是常态)→ 令牌被删掉、退回登录页。
 *    令牌完全有效,删掉之后后端回来也救不回来,用户只能手动重新登录。
 *  · 反过来,把真正的 401 当成"离线"留着令牌的话,一个已经失效的会话会一直卡在重试屏上。
 */
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiOfflineError } from "@/api/client";
import { AuthProvider, useAuth } from "@/app/auth";

vi.mock("@/api/client", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/api/client")>();
  return {
    ...real,
    api: vi.fn(),
    getAuthToken: () => window.localStorage.getItem("openstudio.auth.token"),
    setAuthToken: (token: string | null) => {
      if (token) window.localStorage.setItem("openstudio.auth.token", token);
      else window.localStorage.removeItem("openstudio.auth.token");
    },
    setUnauthorizedHandler: () => undefined,
  };
});

const { api } = await import("@/api/client");

function Probe() {
  const { status } = useAuth();
  return <span data-testid="status">{status}</span>;
}

function mount() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("启动时够不着后端", () => {
  beforeEach(() => {
    window.localStorage.setItem("openstudio.auth.token", "still-good");
    vi.mocked(api).mockReset();
  });

  it("连不上时**保住令牌**,并且不摆登录页", async () => {
    vi.mocked(api).mockRejectedValue(new ApiOfflineError("连不上"));
    mount();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("offline"));
    expect(window.localStorage.getItem("openstudio.auth.token")).toBe("still-good");
  });

  it("服务端真的拒了才登出 —— 那时令牌确实不该留着", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Not authenticated"));
    mount();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("anonymous"));
    expect(window.localStorage.getItem("openstudio.auth.token")).toBeNull();
  });
});
