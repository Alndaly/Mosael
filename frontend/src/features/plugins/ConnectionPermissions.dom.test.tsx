/** @vitest-environment jsdom */

/**
 * 插件升级后多要了权限:已有的连接停用 —— 这是有意的,但界面要说清楚**为什么停了、多要了哪几项、点哪里恢复**,
 * 不能只剩一句「用不了」让人以为插件坏了。刚接上的连接还没授权,是另一种说法。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { setPluginPermissions } = vi.hoisted(() => ({ setPluginPermissions: vi.fn() }));
vi.mock("@/api/client", () => ({ setPluginPermissions }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      pluginPermNetwork: "连接 {scope}",
      pluginPermFsWrite: "写入本机文件",
    })[key] ?? key,
}));

import type { PluginInstance } from "@/api/client";
import { ConnectionPermissionNotice, waitingForPermissions } from "./ConnectionPermissions";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(node, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

const upgraded = {
  id: "c1",
  name: "ComfyUI · 192.168.3.15",
  enabled: true,
  blocked_reason: "插件更新后多要了 2 项权限……",
  pending_permissions: ["network:huggingface", "filesystem:write"],
  permissions_added: true,
} as unknown as PluginInstance;

beforeEach(() => {
  setPluginPermissions.mockReset();
  setPluginPermissions.mockResolvedValue([]);
});

describe("连接上的权限提示", () => {
  it("升级后多要了权限:说停用了、多要了哪几项(人话 + 原码)、一键授予这几项", async () => {
    wrap(<ConnectionPermissionNotice instance={upgraded} />);
    const notice = screen.getByRole("alert");
    expect(notice.textContent).toContain("pluginPermAddedTitle");
    expect(notice.textContent).toContain("pluginPermAddedBody");
    expect(notice.textContent).toContain("连接 huggingface");
    expect(notice.textContent).toContain("network:huggingface");
    expect(notice.textContent).toContain("写入本机文件");
    expect(notice.textContent).toContain("filesystem:write");
    fireEvent.click(screen.getByRole("button", { name: "pluginPermGrantAll" }));
    await waitFor(() =>
      expect(setPluginPermissions).toHaveBeenCalledWith("c1", {
        grants: { "network:huggingface": true, "filesystem:write": true },
      }),
    );
  });

  it("刚接上的连接还没授权:是另一种说法", () => {
    wrap(<ConnectionPermissionNotice instance={{ ...upgraded, permissions_added: false } as PluginInstance} />);
    expect(screen.getByRole("alert").textContent).toContain("pluginPermPendingTitle");
    expect(screen.queryByText("pluginPermAddedTitle")).toBeNull();
  });

  it("不缺权限就什么都不摆", () => {
    const { container } = wrap(
      <ConnectionPermissionNotice instance={{ ...upgraded, pending_permissions: [], permissions_added: false } as PluginInstance} />,
    );
    expect(container.textContent).toBe("");
  });

  it("插件列表上标出「待授权」:启用着、却因为缺权限停了的连接", () => {
    expect(waitingForPermissions([upgraded])).toBe(true);
    expect(waitingForPermissions([{ ...upgraded, enabled: false } as PluginInstance])).toBe(false);
    expect(waitingForPermissions([{ ...upgraded, pending_permissions: [] } as PluginInstance])).toBe(false);
  });
});
