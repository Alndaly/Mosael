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
  install?: {
    available: boolean;
    target: string;
    version: string;
    archives: number;
    reason: string;
    detail: string;
    installed: string;
  };
};

const BREW: Settings = {
  path: "",
  in_use: "ffmpeg",
  pinned_by_environment: false,
  found: true,
  version: "9.0.2",
  libass: false,
  text_burn_in: null,
  install: { available: true, target: "darwin-arm64", version: "9.0.2", archives: 2, reason: "", detail: "", installed: "" },
};
const FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg";

let stored: Settings = BREW;
const puts: string[] = [];
let rechecks = 0;
let installs = 0;
//: 那颗安装任务:起来之后按 running → succeeded 走一遍(进度那一行据此说话)。
let task: { id: string; status: string; progress: number; error: string | null } = { id: "j1", status: "running", progress: 0.4, error: null };
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
    if (url === "/api/settings/ffmpeg/install") {
      installs += 1;
      return Promise.resolve({ id: task.id });
    }
    if (url === "/api/jobs/j1") {
      if (!task) return Promise.reject(new Error("no task"));
      return Promise.resolve({ ...task, message_key: "jobMsg_mediaToolDownloading" });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  },
}));

const { FfmpegSection } = await import("./FfmpegSection");

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FfmpegSection workspaceId="w1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  stored = BREW;
  puts.length = 0;
  rechecks = 0;
  installs = 0;
  task = { id: "j1", status: "running", progress: 0.4, error: null };
});

//: 维护者:「Mosael 不具备主动下载 ffmpeg-full 的能力,应该补充这部分能力,否则用户必须自行在别处下载」。
it("现在这个烧不了字、清单里又有构建:摆「让 Mosael 装一个完整版」,按下之后跟着那颗任务走", async () => {
  show();
  const button = await screen.findByRole("button", { name: "ffmpegInstallAction" });
  //: 这一行的说明与「装的是哪个构建」两处文案都在(文案里的 {version} / {target} 由真文案渲染)
  expect(screen.getByText("ffmpegInstallDesc")).toBeInTheDocument();
  expect(screen.getByText("ffmpegInstallTarget")).toBeInTheDocument();

  fireEvent.click(button);
  await waitFor(() => expect(installs).toBe(1));
  expect(await screen.findByText("ffmpegInstallWorking")).toBeInTheDocument();

  task = { id: "j1", status: "failed", progress: 0.4, error: "摘要对不上(ffmpeg.zip)" };
  expect(await screen.findByText("ffmpegInstallFailed", {}, { timeout: 4000 })).toBeInTheDocument();
  expect(await screen.findByText(/摘要对不上/, {}, { timeout: 4000 })).toBeInTheDocument();
});

it("现在这个就能烧字:不摆那一行 —— 能用的时候摆一颗按钮只会让人以为要手动做点什么", async () => {
  stored = { ...BREW, libass: true, text_burn_in: "libass" };
  show();
  await screen.findByText("ffmpegHasLibass");
  expect(screen.queryByRole("button", { name: "ffmpegInstallAction" })).toBeNull();
});

it("这个平台没有对得上的构建:也不摆(后端那句话留给手填路径那条路)", async () => {
  stored = { ...BREW, install: { available: false, target: "freebsd-x86_64", version: "", archives: 0, reason: "mediaToolErr_noBuild", detail: "freebsd", installed: "" } };
  show();
  await screen.findByText("ffmpegNoTextBurnIn");
  expect(screen.queryByRole("button", { name: "ffmpegInstallAction" })).toBeNull();
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
