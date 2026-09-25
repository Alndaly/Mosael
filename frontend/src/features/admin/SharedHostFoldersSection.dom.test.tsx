/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

/**
 * 共享给成员的本机文件夹:列出来的是后端存的真实路径,加一条 / 去一条都是整份清单 PUT 回去 ——
 * 后端负责校验与展开,这里不自己拼路径。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const calls: Array<{ path: string; init?: RequestInit }> = [];
let stored = ["/Users/me/Shared"];
vi.mock("@/api/client", () => ({
  getSharedHostFolders: () => {
    calls.push({ path: "get" });
    return Promise.resolve({ folders: stored });
  },
  setSharedHostFolders: (folders: string[]) => {
    calls.push({ path: "put", init: { method: "PUT", body: JSON.stringify({ folders }) } });
    stored = folders;
    return Promise.resolve({ folders: stored });
  },
}));

const { SharedHostFoldersSection } = await import("./SharedHostFoldersSection");

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SharedHostFoldersSection />
    </QueryClientProvider>,
  );
}

it("加一条、去一条都把整份清单交给后端", async () => {
  show();
  expect(await screen.findByText("/Users/me/Shared")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("deploySharedFoldersNew"), { target: { value: "/Volumes/Footage" } });
  fireEvent.click(screen.getByRole("button", { name: /deploySharedFoldersAdd/ }));
  await waitFor(() => expect(screen.getByText("/Volumes/Footage")).toBeInTheDocument());
  expect(JSON.parse(String(calls.find((call) => call.init?.method === "PUT")?.init?.body))).toEqual({
    folders: ["/Users/me/Shared", "/Volumes/Footage"],
  });

  fireEvent.click(screen.getAllByRole("button", { name: "deploySharedFoldersRemove" })[0]);
  await waitFor(() => expect(screen.queryByText("/Users/me/Shared")).not.toBeInTheDocument());
  expect(stored).toEqual(["/Volumes/Footage"]);
});
