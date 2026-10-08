/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 管理 → 引擎 → FFmpeg(ADR 0048):启动时探出来的结论摆在界面上,填的路径交给后端判。
 *
 * - Homebrew 默认的 ffmpeg(没有 libass)、浏览器那条路又不通:说带字的导出会被拒,和怎么办(装完整版、填路径);
 * - 浏览器那条路通:没有 libass 也只是一句平静的说明;
 * - 找不到 ffmpeg:说找不到;
 * - 环境变量钉住了:那一格不能填,说为什么;
 * - 填的路径被后端挡下:那句话贴着输入框留着,一改就消失;存下之后显示新探出来的样子。
 */

const t = (key: string) => key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

type Settings = {
  path: string;
  in_use: string;
  pinned_by_environment: boolean;
  found: boolean;
  version: string;
  libass: boolean;
  text_burn_in: string | null;
};

const BREW: Settings = {
  path: "",
  in_use: "ffmpeg",
  pinned_by_environment: false,
  found: true,
  version: "9.0.2",
  libass: false,
  text_burn_in: null,
};
const FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg";

let stored: Settings = BREW;
const puts: string[] = [];
let rechecks = 0;
vi.mock("@/api/client", () => ({
  api: (url: string, init?: { method?: string; body?: string }) => {
    if (url === "/api/settings/ffmpeg" && !init) return Promise.resolve(stored);
    if (url === "/api/settings/ffmpeg" && init?.method === "PUT") {
      const { path } = JSON.parse(init.body ?? "{}") as { path: string };
      puts.push(path);
      if (!path.startsWith("/")) return Promise.reject(new Error(`要填完整路径:${path}`));
      stored = { ...stored, path, in_use: path, version: "8.0", libass: true, text_burn_in: "libass" };
      return Promise.resolve(stored);
    }
    if (url === "/api/settings/ffmpeg/recheck") {
      rechecks += 1;
      return Promise.resolve(stored);
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  },
}));

const { FfmpegSection } = await import("./FfmpegSection");

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FfmpegSection />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  stored = BREW;
  puts.length = 0;
  rechecks = 0;
});

it("Homebrew 的精简版、浏览器那条路又不通:说带字的导出会被拒,和怎么办", async () => {
  show();
  expect(await screen.findByText("ffmpegNoTextBurnIn")).toBeInTheDocument();
  expect(screen.getByText("ffmpegNoLibass")).toBeInTheDocument();
  expect(screen.getByText("ffmpeg")).toBeInTheDocument();
  expect(screen.getByText(/ffmpegVersion/)).toBeInTheDocument();
  expect(screen.queryByText("ffmpegTextByBrowser")).not.toBeInTheDocument();
});

it("浏览器那条路通:没有 libass 也只是说明一句,不报警", async () => {
  stored = { ...BREW, text_burn_in: "browser" };
  show();
  expect(await screen.findByText("ffmpegTextByBrowser")).toBeInTheDocument();
  expect(screen.queryByText("ffmpegNoTextBurnIn")).not.toBeInTheDocument();
});

it("找不到 ffmpeg:说找不到", async () => {
  stored = { ...BREW, found: false, version: "" };
  show();
  expect(await screen.findByText("ffmpegNotFound")).toBeInTheDocument();
  expect(screen.getByText("ffmpegMissingState")).toBeInTheDocument();
  expect(screen.queryByText("ffmpegNoTextBurnIn")).not.toBeInTheDocument();
});

it("环境变量钉住了:那一格不能填,说为什么;报错说改环境变量", async () => {
  stored = { ...BREW, pinned_by_environment: true, in_use: "/usr/local/bin/ffmpeg" };
  show();
  expect(await screen.findByText("ffmpegPathPinned")).toBeInTheDocument();
  expect(screen.getByText("ffmpegNoTextBurnInPinned")).toBeInTheDocument();
  expect(screen.getByLabelText("ffmpegPathLabel")).toBeDisabled();
});

it("填的路径被挡下:那句话贴着输入框,一改就消失;存下之后显示新探出来的样子", async () => {
  show();
  const input = await screen.findByLabelText("ffmpegPathLabel");
  await waitFor(() => expect(input).not.toBeDisabled());

  fireEvent.change(input, { target: { value: "bin/ffmpeg" } });
  fireEvent.click(screen.getByRole("button", { name: "save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("要填完整路径:bin/ffmpeg");
  expect(input).toHaveAttribute("aria-invalid", "true");
  fireEvent.change(input, { target: { value: ` ${FULL} ` } });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "save" }));
  expect(await screen.findByText("ffmpegHasLibass")).toBeInTheDocument();
  expect(puts).toEqual(["bin/ffmpeg", FULL]);
  expect(screen.queryByText("ffmpegNoTextBurnIn")).not.toBeInTheDocument();
  expect(screen.getByText(FULL, { selector: "code" })).toBeInTheDocument();
});

it("重新检测:问后端再探一次", async () => {
  show();
  await screen.findByText("ffmpegNoTextBurnIn");
  stored = { ...BREW, libass: true, text_burn_in: "libass" };
  fireEvent.click(screen.getByRole("button", { name: /ffmpegRecheck/ }));
  expect(await screen.findByText("ffmpegHasLibass")).toBeInTheDocument();
  expect(rechecks).toBe(1);
});
