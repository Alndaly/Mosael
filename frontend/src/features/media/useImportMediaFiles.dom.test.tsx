/** @vitest-environment jsdom */
/**
 * 一次导入一批文件:逐个传,一个失败不拦后面的,最后说清进来几个、哪个没进来。
 * 此前素材页的「导入」按钮只收选择框里的第一个文件,其余的一声不响地丢了。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  importAsset: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/api/client", async (original) => ({ ...(await original<typeof import("@/api/client")>()), importAsset: mocks.importAsset }));
vi.mock("sonner", () => ({ toast: { success: mocks.success, error: mocks.error } }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key === "mediaImportPartial" ? "{n}|{m}|{name}|{reason}" : `${key}:{n}` }));

import { useImportMediaFiles } from "./useImportMediaFiles";

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}
const file = (name: string) => new File(["x"], name);

it("逐个导入,不并发;中间一个失败,后面的照样进来,并说清是哪个", async () => {
  let inFlight = 0;
  let maxInFlight = 0;
  mocks.importAsset.mockImplementation(async ({ file: one }: { file: File }) => {
    inFlight += 1;
    maxInFlight = Math.max(maxInFlight, inFlight);
    await new Promise((resolve) => setTimeout(resolve, 1));
    inFlight -= 1;
    if (one.name === "bad.xyz") throw new Error("不支持的格式");
    return { id: one.name };
  });
  const { result } = renderHook(() => useImportMediaFiles({ workspaceId: "ws", projectId: "p1" }), { wrapper });

  act(() => result.current.mutate([file("a.mp4"), file("bad.xyz"), file("c.png")]));
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  expect(mocks.importAsset.mock.calls.map(([args]) => args.file.name)).toEqual(["a.mp4", "bad.xyz", "c.png"]);
  expect(mocks.importAsset.mock.calls.every(([args]) => args.workspaceId === "ws" && args.projectId === "p1")).toBe(true);
  expect(maxInFlight).toBe(1);
  expect(mocks.error).toHaveBeenCalledWith("2|1|bad.xyz|不支持的格式");
  expect(mocks.success).not.toHaveBeenCalled();
});
