/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 管理 → 下载源:pip、npm 之外,「让 Mosael 装」的两行(ADR 0041 §4)—— PyTorch 源(预设由后端给,官方那一项地址空着)、
 * GitHub 镜像前缀(离开框时才存,清空就是直连)。写得对不对由后端判。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const updates: Record<string, string>[] = [];
let stored: Record<string, unknown> = {};
vi.mock("@/api/client", () => ({
  getInstallSource: () => Promise.resolve(stored),
  updateInstallSource: (body: Record<string, string>) => {
    updates.push(body);
    stored = { ...stored, ...body };
    return Promise.resolve(stored);
  },
}));

const { InstallSourceSection } = await import("./InstallSourceSection");

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InstallSourceSection />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  updates.length = 0;
  stored = {
    pip_index: "", npm_registry: "", pip_presets: [], npm_presets: [], pytorch_index: "", github_mirror: "",
    pytorch_presets: [
      { value: "pytorch", label: "官方(download.pytorch.org)", url: "" },
      { value: "nju", label: "南京大学", url: "https://mirror.nju.edu.cn/pytorch/whl" },
    ],
  };
});

it("PyTorch 源和 GitHub 镜像前缀两行都在;空的 PyTorch 源就是官方那一项", async () => {
  show();
  expect(await screen.findByText("installSourcePytorch")).toBeTruthy();
  expect(screen.getByText("installSourcePytorchHint")).toBeTruthy();
  expect(await screen.findByText("官方(download.pytorch.org)")).toBeTruthy();
  expect(screen.getByText("installSourceGithub")).toBeTruthy();
  expect(screen.getByLabelText("installSourceGithub").getAttribute("placeholder")).toBe("installSourceGithubPlaceholder");
});

it("GitHub 镜像前缀离开框时才存,去掉两头空白;没改不存", async () => {
  show();
  const input = (await screen.findByLabelText("installSourceGithub")) as HTMLInputElement;
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: " https://gh.example " } });
  expect(updates, "敲字的时候不存").toEqual([]);
  fireEvent.blur(input);
  await waitFor(() => expect(updates).toEqual([{ github_mirror: "https://gh.example" }]));
  await waitFor(() => expect(input.value).toBe("https://gh.example"));
  fireEvent.focus(input);
  fireEvent.blur(input);
  expect(updates).toHaveLength(1);
});
