/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 管理 → 引擎 → 降噪:一节看全本机的几种方式,只有要下载的那个有按钮。
 *
 * 默认是**这台机器**的设定(和转写模型、默认克隆引擎同一条规则):说明之后、列表之前**一行整行**
 * (`AdminDefaultSelect`),整节只有那一处能改;列表行只负责下载/状态,已默认的那一行只剩一枚
 * 不可点的淡标记。「能力提供方 → 降噪」里按人选的会覆盖它。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { DenoiseEnginesSection } from "./DenoiseEnginesSection";
import { ADMIN_CARD } from "./adminLayout";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const BASE = {
  installable: false, status: "ready", setup_hint: "", message: "", size_bytes: 0, strengths: [],
  is_default: false,
};
const rows = (deepfilter: Record<string, unknown> = {}, rnnoise: Record<string, unknown> = {}) => [
  // 这个人配好的降噪插件(ADR 0032):id 是连接 id。它是某个成员自己的连接,不是这台机器上装的引擎。
  { ...BASE, engine: "conn-42", label: "某降噪插件", description: "插件", ready: true, removes_music: false },
  { ...BASE, engine: "builtin:ffmpeg", label: "内置降噪", description: "去底噪", ready: true, removes_music: false },
  {
    ...BASE, engine: "builtin:deepfilternet", label: "DeepFilterNet", description: "效果最好", ready: false,
    installable: true, status: "missing", size_bytes: 27_877_081, removes_music: true, ...deepfilter,
  },
  {
    ...BASE, engine: "builtin:rnnoise", label: "RNNoise", description: "轻量;**背景音乐也会被当成噪声去掉**",
    ready: false, status: "unavailable", setup_hint: "ffmpeg 不带这个滤镜", removes_music: true, ...rnnoise,
  },
];

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

/** 默认那一行(整行卡片);还没画出来时返回 null。 */
const defaultLine = (): HTMLElement | null => document.querySelector("[data-admin-default-line]");

function renderSection(deepfilter: Record<string, unknown> = {}, rnnoise: Record<string, unknown> = {}) {
  let data = rows(deepfilter, rnnoise);
  const posts: string[] = [];
  const puts: Array<{ url: string; body: unknown }> = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "PUT") {
      puts.push({ url, body: JSON.parse(String(init.body)) });
      const wanted = JSON.parse(String(init.body)).engine as string;
      // 后端真的存下来了:再问一次列表时,新答案就是它。
      data = data.map((row) => ({ ...row, is_default: row.engine === wanted }));
      return json(data.find((row) => row.engine === wanted));
    }
    if (init?.method === "POST") {
      posts.push(url);
      return json(rows({ status: "installing" })[2]);
    }
    return json(data);
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DenoiseEnginesSection />
    </QueryClientProvider>,
  );
  return { posts, puts };
}

/** 引擎自己那一行 —— 默认行里也有引擎名(下拉的当前值),得先把它排除掉。
 *  选了默认之后,屏幕上有两处同名文字(触发器 + 列表行),所以用 findAll 而不是 find。 */
const rowOf = async (label: string) => {
  await screen.findAllByText(label);
  const row = [...document.querySelectorAll<HTMLElement>("[data-admin-row]")]
    .filter((one) => one.closest("[data-admin-default-line]") === null)
    .find((one) => within(one).queryByText(label));
  if (!row) throw new Error(`没有「${label}」那一行`);
  return row;
};

describe("降噪引擎", () => {
  it("只有要下载的那个有下载按钮,点了就装", async () => {
    const user = userEvent.setup();
    const { posts } = renderSection();
    const deepfilter = await rowOf("DeepFilterNet");
    expect(within(deepfilter).getByText(/denoiseSizeApprox/)).toBeInTheDocument();
    await user.click(within(deepfilter).getByRole("button", { name: /denoiseInstall/ }));
    await waitFor(() => expect(posts).toEqual(["/api/denoise/engines/builtin%3Adeepfilternet/install"].map((path) => expect.stringContaining(path))));
    expect(within(await rowOf("内置降噪")).queryByRole("button")).toBeNull();
  });

  it("会去掉音乐的标出来,不需要装但用不了的说清原因", async () => {
    renderSection();
    const rnnoise = await rowOf("RNNoise");
    expect(rnnoise).toHaveTextContent("denoiseRemovesMusicBadge");
    expect(rnnoise).toHaveTextContent("ffmpeg 不带这个滤镜");
    expect(rnnoise).toHaveTextContent("denoiseUnavailableLabel");
    expect(await rowOf("内置降噪")).not.toHaveTextContent("denoiseRemovesMusicBadge");
  });

  it("失败原因原样显示,按钮变成重试", async () => {
    renderSection({ status: "failed", message: "下载到的文件校验不符" });
    const deepfilter = await rowOf("DeepFilterNet");
    expect(deepfilter).toHaveTextContent("下载到的文件校验不符");
    expect(within(deepfilter).getByRole("button", { name: /denoiseRetry/ })).toBeInTheDocument();
  });

  it("这个平台没有发布文件时直说,不摆按钮", async () => {
    renderSection({ status: "unsupported" });
    const deepfilter = await rowOf("DeepFilterNet");
    expect(deepfilter).toHaveTextContent("denoiseUnsupported");
    expect(within(deepfilter).queryByRole("button")).toBeNull();
  });

  it("每个引擎是卡片里的一行,自己不再套一个框", async () => {
    renderSection();
    const row = await rowOf("DeepFilterNet");
    // 直接挂在卡片下面 —— 分隔线由卡片画,行自己不带框。
    expect(row.parentElement?.className).toBe(ADMIN_CARD);
    expect(row).not.toHaveClass("border");
    expect(row).not.toHaveClass("rounded-lg");
    // 「会去掉音乐」是安静的语义色淡底标签,不是描边的大写小标。
    const tag = within(row).getByText("denoiseRemovesMusicBadge");
    expect(tag).toHaveAttribute("data-admin-tag");
    expect(tag).not.toHaveClass("border");
    expect(tag).not.toHaveClass("uppercase");
  });

  it("只列本机引擎,不列成员自己配的降噪插件", async () => {
    renderSection();
    await rowOf("DeepFilterNet");
    expect(screen.queryByText("某降噪插件")).toBeNull();
  });

  it("装好了显示已安装", async () => {
    renderSection({ status: "installed", ready: true });
    expect(await rowOf("DeepFilterNet")).toHaveTextContent("denoiseInstalled");
  });
});

describe("降噪的默认引擎:说明之后、列表之前的一整行", () => {
  it("三种实现各有默认可设 —— 摆的是选择器,不是「只有一种引擎」那句话", async () => {
    renderSection();
    await rowOf("DeepFilterNet");

    const line = defaultLine();
    expect(line).not.toBeNull();
    expect(line!.dataset.defaultKind).toBe("choice");
    expect(line!.className, "和「模型下载源」同一张整行卡片").toBe(ADMIN_CARD);
    //: 有 3 家可选;别套用单实现那句话。
    expect(screen.queryByText("defaultOnlyOneEngine")).toBeNull();
    expect(within(line!).getByText("denoiseDefaultTitle")).toBeInTheDocument();
    expect(within(line!).getByText("denoiseDefaultHint")).toBeInTheDocument();
  });

  it("位置在节说明之后、引擎列表之前", async () => {
    renderSection();
    await rowOf("DeepFilterNet");

    const section = document.querySelector('[data-admin-section="engine-denoise"]') as HTMLElement;
    const line = defaultLine()!;
    expect(line.previousElementSibling).toBe(section.querySelector("header"));
    expect(line.nextElementSibling?.className).toBe(ADMIN_CARD);
    expect(line.nextElementSibling?.querySelector("[data-admin-row]")).not.toBeNull();
  });

  it("下拉里是当前部署默认;选另一个已安装的 → 写 /api/settings/denoise,列表重读,标记跟着过去", async () => {
    const user = userEvent.setup();
    const { puts } = renderSection({ status: "installed", ready: true }, { ready: true, status: "ready" });
    await rowOf("DeepFilterNet");

    const line = defaultLine()!;
    const trigger = within(line).getByRole("combobox", { name: "denoiseDefaultTitle" });
    //: 还没设过:显示"自动"。
    expect(trigger).toHaveTextContent("denoiseDefaultAuto");

    await user.click(trigger);
    await user.click(await screen.findByRole("option", { name: "RNNoise" }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].url).toContain("/api/settings/denoise");
    expect(puts[0].body).toEqual({ engine: "builtin:rnnoise" });
    await waitFor(() =>
      expect(within(defaultLine()!).getByRole("combobox", { name: "denoiseDefaultTitle" })).toHaveTextContent("RNNoise"),
    );
    //: 已默认只是列表行上的一枚淡标记,不可点;整节只有这一个能写。
    await waitFor(async () => expect(await rowOf("RNNoise")).toHaveTextContent("defaultCurrent"));
    expect(within(defaultLine()!).getAllByRole("combobox")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "defaultCurrent" })).toBeNull();
  });

  it("未安装的引擎在选项里禁用,并写着为什么(DeepFilterNet 要先下载)", async () => {
    const user = userEvent.setup();
    renderSection();
    await rowOf("DeepFilterNet");

    await user.click(within(defaultLine()!).getByRole("combobox", { name: "denoiseDefaultTitle" }));
    const missing = await screen.findByRole("option", { name: /DeepFilterNet/ });
    expect(missing).toHaveAttribute("aria-disabled", "true");
    expect(missing).toHaveTextContent("defaultNotInstalled");
    //: 能用的那一家仍然能选。
    expect(screen.getByRole("option", { name: "内置降噪" })).not.toHaveAttribute("aria-disabled", "true");
  });

  it("不好用但不要下载的(ffmpeg 没有 RNNoise 滤镜)给的是它真正的理由,不是「先下载」", async () => {
    const user = userEvent.setup();
    renderSection();
    await rowOf("RNNoise");

    await user.click(within(defaultLine()!).getByRole("combobox", { name: "denoiseDefaultTitle" }));
    const rnnoise = await screen.findByRole("option", { name: /RNNoise/ });
    expect(rnnoise).toHaveAttribute("aria-disabled", "true");
    expect(rnnoise).toHaveTextContent("ffmpeg 不带这个滤镜");
    expect(rnnoise).not.toHaveTextContent("defaultNotInstalled");
  });

  it("数据还没到时不画那一行 —— 未知不是「只有一种」", async () => {
    globalThis.fetch = vi.fn(() => new Promise<never>(() => {})) as never;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <DenoiseEnginesSection />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("connecting")).toBeInTheDocument();
    expect(defaultLine()).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("列表行不承担设默认:没有「设为默认」这类按钮", async () => {
    renderSection();
    await rowOf("DeepFilterNet");
    expect(screen.queryByRole("button", { name: /defaultTitle|设为默认|setDefault/i })).toBeNull();
  });
});

it("引擎说明里的 **强调** 渲染成粗体,不露星号", async () => {
  renderSection();
  const row = await rowOf("RNNoise");
  expect(within(row).getByText("背景音乐也会被当成噪声去掉").tagName).toBe("STRONG");
  expect(row.textContent).not.toContain("**");
});
