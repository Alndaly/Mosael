/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { zhCN } from "@/app/messages/zh-CN";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import { ADMIN_CARD } from "./adminLayout";

/**
 * 管理 → 引擎 → FFmpeg(ADR 0048):启动时探出来的结论摆在界面上,填的路径交给后端判。
 *
 * - Homebrew 默认的 ffmpeg(没有 libass)、浏览器那条路又不通:说带字的导出会被拒,和怎么办(装完整版、填路径);
 * - 浏览器那条路通:没有 libass 也只是一句平静的说明;
 * - 找不到 ffmpeg:说找不到;
 * - 环境变量钉住了:那一格不能填,说为什么;
 * - 填的路径被后端挡下:那句话贴着输入框留着,一改就消失;存下之后显示新探出来的样子。
 *
 * 版式:路径这一行和这一页别的行(以及「TTS 解释器」那一格)同一套语法 —— 一张 ADMIN_CARD、
 * 左边标题 + 说明、右边控件格,保存按钮就在输入框旁边那一格(整节只有它一颗)。
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

//: 维护者:「这个 ffmpeg 这里的相关 UI 和配置是否有点问题」。**有问题**:
//: 说明写着「填的不生效」,那一格却还是能填的样子、placeholder 还写「留空:用 PATH 上的 ffmpeg」——
//: 一行里两种优先级在说话。环境变量钉住时这一格不该是「能填但没用」。
it("环境变量钉住了:那一格不能填、说明为什么、说清去哪改;placeholder 不再提「留空=PATH」", async () => {
  // 存过的路径还在:钉住时它不生效,但这一格显示的仍是库里那份。
  stored = { ...BREW, path: "/usr/bin/ffmpeg", pinned_by_environment: true, in_use: "/usr/local/bin/ffmpeg" };
  show();
  // 说明:为什么(原文)+ 去哪改(改环境变量,不是这页)
  expect(await screen.findByText("ffmpegPathPinned")).toBeInTheDocument();
  expect(screen.getByText("ffmpegPathPinnedWhere")).toBeInTheDocument();
  expect(screen.getByText("ffmpegNoTextBurnInPinned")).toBeInTheDocument();

  const input = screen.getByLabelText("ffmpegPathLabel");
  // ① 打不了字 —— 打不了字就不会骗人
  expect(input).toBeDisabled();
  // ② placeholder 换成「由环境变量决定」,不再说「留空:用 PATH 上的 ffmpeg」
  expect(input).toHaveAttribute("placeholder", "ffmpegPathPlaceholderPinned");
  expect(input.getAttribute("placeholder")).not.toBe("ffmpegPathPlaceholder");

  // ⑤ 禁用态有可读的原因:aria-describedby 指着那句说明(不是只有灰)
  const describedBy = input.getAttribute("aria-describedby");
  expect(describedBy).toBeTruthy();
  const reason = document.getElementById(describedBy!);
  expect(reason).not.toBeNull();
  expect(reason).toHaveTextContent("ffmpegPathPinned");

  // 保存:这一格打不了字 → 永远不 dirty → 保持禁用(不是新长出来的一颗按钮)
  expect(screen.getByRole("button", { name: "save" })).toBeDisabled();
  // 「重新检测」和路径字段无关,照样能按
  expect(screen.getByRole("button", { name: /ffmpegRecheck/ })).not.toBeDisabled();
});

it("没钉住时行为一点不变:能填、placeholder 还是「留空:用 PATH 上的 ffmpeg」、保存按 dirty", async () => {
  stored = { ...BREW, path: "" };
  show();
  const input = await screen.findByLabelText("ffmpegPathLabel");
  await waitFor(() => expect(input).not.toBeDisabled());
  // 没钉住:placeholder 原样(真文案另钉一次),也没有那句「由环境变量决定」
  expect(input).toHaveAttribute("placeholder", "ffmpegPathPlaceholder");
  // 没钉住、也没报错:不挂 aria-describedby(它只给禁用态和报错用)
  expect(input).not.toHaveAttribute("aria-describedby");

  const saveButton = screen.getByRole("button", { name: "save" });
  expect(saveButton).toBeDisabled();
  fireEvent.change(input, { target: { value: FULL } });
  expect(saveButton).not.toBeDisabled();
  // 只剩空白:trim 之后和库里那份一样 → 又回到不 dirty
  fireEvent.change(input, { target: { value: "   " } });
  expect(saveButton).toBeDisabled();

  expect((zhCN as Record<string, string>).ffmpegPathPlaceholder).toBe("留空:用 PATH 上的 ffmpeg");
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

/** 路径那一行 —— 从输入框往上找最近的 AdminRow(行里也会出现别的行,不能只按文字找)。 */
function pathRow(): HTMLElement {
  const input = screen.getByLabelText("ffmpegPathLabel");
  const row = input.closest<HTMLElement>("[data-admin-row]");
  if (!row) throw new Error("「ffmpeg 路径」的输入框不在一个 [data-admin-row] 里");
  return row;
}

//: 维护者:「ffmpeg路径的配置」和「TTS 解释器(可选)」这两个表单的风格不一致 咋回事。
//: TTS 那一格是 ADMIN_CARD 里的 AdminRow:左边标题 + 说明,右边控件。这一节此前把控件堆在字下面、
//: 占满整行 —— 同一页两套行语法。下面钉住改后的样子。
it("路径这一行照抄「TTS 解释器」:一张 ADMIN_CARD 里的 AdminRow,左边标题 + 说明、右边控件格", async () => {
  show();
  const input = await screen.findByLabelText("ffmpegPathLabel");
  const row = pathRow();
  //: 和别的行同一张卡片(ADMIN_CARD),不是自己写的一行。
  expect(row.parentElement?.className).toBe(ADMIN_CARD);
  //: 左格:标题 + 说明(不是把说明塞进右格)。
  expect(within(row).getByText("ffmpegPathLabel")).toBeInTheDocument();
  expect(row.querySelector("[data-admin-row-description]")).toHaveTextContent("ffmpegPathDesc");
  //: 右格:控件格,输入框和保存按钮都在里面;控件格是这一行的直接孩子(左字右控件,不是上下堆)。
  const control = row.querySelector<HTMLElement>("[data-admin-row-control]");
  expect(control).not.toBeNull();
  expect(control!.parentElement).toBe(row);
  expect(within(control!).getByLabelText("ffmpegPathLabel")).toBe(input);
  expect(within(control!).getByRole("button", { name: "save" })).toBeInTheDocument();
});

it("输入框和「TTS 解释器」一样宽:同一个 SETTINGS_FIELD_WIDTH", async () => {
  show();
  const input = await screen.findByLabelText("ffmpegPathLabel");
  expect(input.className).toContain(SETTINGS_FIELD_WIDTH);
  expect(input).toHaveClass("font-mono");
});

it("保存按钮只有一处:在输入框右边那一格,不在整节底部再放一颗", async () => {
  show();
  await screen.findByLabelText("ffmpegPathLabel");
  const saves = screen.getAllByRole("button", { name: "save" });
  expect(saves).toHaveLength(1);
  expect(pathRow().querySelector("[data-admin-row-control]")).toContainElement(saves[0]);
});

it("钉住时的真文案:为什么照旧,后面补一句去哪改;placeholder 由环境变量决定", async () => {
  stored = { ...BREW, pinned_by_environment: true };
  show();
  expect(await screen.findByText("ffmpegPathPinned")).toBeInTheDocument();
  expect(pathRow().querySelector("[data-admin-row-description]")).toHaveTextContent("ffmpegPathPinned");
  const zh = zhCN as Record<string, string>;
  //: 为什么:原文照旧(环境变量已经指定了 ffmpeg,这里填的不生效)。
  expect(zh.ffmpegPathPinned).toBe("环境变量 MOSAEL_FFMPEG 已经指定了 ffmpeg,这里填的不生效。");
  //: 去哪改:改环境变量、重启 —— 不指向这一页上任何一颗按钮(这页没有「改环境变量」的地方)。
  expect(zh.ffmpegPathPinnedWhere).toContain("环境变量 MOSAEL_FFMPEG");
  expect(zh.ffmpegPathPinnedWhere).toContain("重启");
  expect(zh.ffmpegPathPinnedWhere).not.toMatch(/下面的|上面的|点击|按钮/);
  //: placeholder 不再说「留空 = PATH」:环境变量说了算,这格留空也轮不到 PATH。
  expect(zh.ffmpegPathPlaceholderPinned).toBe("由环境变量决定");
  expect(zh.ffmpegPathPlaceholderPinned).not.toContain("PATH");
  expect(zh.ffmpegPathPlaceholderPinned).not.toContain("留空");
});
