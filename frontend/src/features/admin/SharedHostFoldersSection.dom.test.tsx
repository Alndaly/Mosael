/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 共享给成员的本机文件夹:列出来的是后端存的真实路径,加一条 / 去一条都是整份清单 PUT 回去 ——
 * 后端负责校验与展开,这里不自己拼路径。加一条走弹窗,后端挡下来的那句话留在弹窗里。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const puts: string[][] = [];
let stored: string[] = [];
vi.mock("@/api/client", () => ({
  getSharedHostFolders: () => Promise.resolve({ folders: stored }),
  setSharedHostFolders: (folders: string[]) => {
    puts.push(folders);
    if (folders.includes("relative/path")) return Promise.reject(new Error("not an absolute path"));
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

beforeEach(() => {
  puts.length = 0;
  stored = ["/Users/me/Shared"];
});

it("加一条、去一条都把整份清单交给后端", async () => {
  show();
  expect(await screen.findByText("/Users/me/Shared")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /deploySharedFoldersNew/ }));
  const dialog = await screen.findByRole("dialog");
  const input = within(dialog).getByLabelText(/deploySharedFoldersPath/);
  fireEvent.change(input, { target: { value: "/Volumes/Footage" } });
  // 回车提交;输入法组词中的回车不算。
  fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
  expect(puts).toEqual([]);
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(screen.getByText("/Volumes/Footage")).toBeInTheDocument());
  expect(puts).toEqual([["/Users/me/Shared", "/Volumes/Footage"]]);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

  fireEvent.click(screen.getAllByRole("button", { name: "deploySharedFoldersRemove" })[0]);
  await waitFor(() => expect(screen.queryByText("/Users/me/Shared")).not.toBeInTheDocument());
  expect(stored).toEqual(["/Volumes/Footage"]);
});

it("后端挡下来的那句话留在弹窗里,贴着输入框;一改输入就消失", async () => {
  show();
  await screen.findByText("/Users/me/Shared");
  fireEvent.click(screen.getByRole("button", { name: /deploySharedFoldersNew/ }));
  const dialog = await screen.findByRole("dialog");
  const input = within(dialog).getByLabelText(/deploySharedFoldersPath/);
  fireEvent.change(input, { target: { value: "relative/path" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "deploySharedFoldersAdd" }));

  expect(await within(dialog).findByRole("alert")).toHaveTextContent("not an absolute path");
  expect(input).toHaveAttribute("aria-invalid", "true");
  fireEvent.change(input, { target: { value: "/abs" } });
  expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
});

it("一个都没共享时是空态,不是一条空列表", async () => {
  stored = [];
  show();
  expect(await screen.findByText("deploySharedFoldersEmpty")).toBeInTheDocument();
});
