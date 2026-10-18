/** @vitest-environment jsdom */

/**
 * 工作台「缺失项」里一个缺的模型那一块(见 ModelDownload):
 *
 * - 工作流写了下载地址:把**那个地址本身**常显在「下载」那一行的下面 —— 完整、可折行、可点、可复制,
 *   **不靠悬停浮层**(工作台那一列的说明默认朝左,长地址会飘到画布上);没写地址就没有这一行,不摆空占位;
 * - 多平台:只在**能确认是同一个文件**时给。工作流声明的 SHA256 是该平台元数据里也记着的那个(搜索插件的
 *   `confirmed` 只在这一条上给)才列出来,并把那个 SHA256 交给下载,下完再核对。没有 SHA256(也没有该平台的明确
 *   id)就不查、不列 —— 不靠文件名相近冒充;查询失败 / 离线只是不出现,原来那个地址照样能下。
 */

import React from "react";
import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getModelLibrary: vi.fn(),
  resolveModelLink: vi.fn(),
  searchModelSources: vi.fn(),
  startModelDownload: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  const zh = messages["zh-CN"] as Record<string, string>;
  const t = (key: string) => zh[key] ?? key;
  return { useI18n: () => t, translateNow: t, usePreferences: () => ({ locale: "zh" }) };
});

import { HintRegion, TooltipProvider } from "@/components/ui/tooltip";
import { ModelDownload } from "./ModelDownload";

const TARGET = { instanceId: "i1", instanceName: "ComfyUI · 本机", workspaceId: "w1", url: "http://127.0.0.1:8188" };
const FOLDER = "checkpoints";
const NAME = "flux1-dev-fp8.safetensors";
const DIGEST = "ab".repeat(32);
/** 和 ComfyWorkbench 右边那一列一样:`side: "left"`(桌面版还会经浮层视图画到原生网页视图上面)。 */
const COLUMN_REGION = { side: "left" as const };
/** 200+ 字符的地址:维护者截图里那种 —— 一整行放不下,要能折行,不能被朝左的浮层带走。 */
const HUGE_URL =
  "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/subfolder/models/checkpoints/" +
  "flux1-dev-fp8.safetensors?download=true&revision=main&token=abcdefghijklmnopqrstuvwxyz0123456789" +
  "&filename=flux1-dev-fp8.safetensors&response-content-disposition=attachment";

function library(route = "local") {
  return { folders: [], missing: [], downloads: [], models: [], download: { route, note: "" } };
}

function renderBlock(props: Partial<React.ComponentProps<typeof ModelDownload>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider delayDuration={0}>
        <HintRegion.Provider value={COLUMN_REGION}>
          <ModelDownload target={TARGET} folder={FOLDER} wanted={NAME} doneLabel="下好了" onDone={() => undefined} {...props} />
        </HintRegion.Provider>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

function declared(): HTMLElement | null {
  return document.querySelector<HTMLElement>("[data-declared-url]");
}

/** 走完「下载 → 确认 → 开始下载」,让这一块进入「正在下载」那一行(取消就在那一行上)。 */
async function startDownload(route = "local") {
  api.getModelLibrary.mockResolvedValue(library(route));
  api.resolveModelLink.mockResolvedValue({ source: "civitai", url: "https://civitai.com/api/download/models/7",
                                           filename: NAME, exists: false, uses_token: false, note: "" });
  renderBlock({ url: "https://civitai.com/api/download/models/7" });
  fireEvent.click(await screen.findByRole("button", { name: `下载 ${NAME}` }));
  const confirm = await screen.findByRole("group");
  fireEvent.click(within(confirm).getByRole("button", { name: "开始下载" }));
  await waitFor(() => expect(api.startModelDownload).toHaveBeenCalled());
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.getModelLibrary.mockResolvedValue(library());
  api.searchModelSources.mockResolvedValue({ filename: NAME, candidates: [], failed: [] });
  api.startModelDownload.mockResolvedValue({ id: "job-1", status: "queued" });
  api.getJob.mockResolvedValue({ id: "job-1", status: "running", message: "" });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

// --- 一、显示工作流里写的那个地址 ---------------------------------------------------

describe("工作流写了下载地址", () => {
  it("完整地址常显在下面一行:可点、可复制、200+ 字符折行不省略(不靠悬停浮层)", () => {
    expect(HUGE_URL.length, "这条测的是超长地址").toBeGreaterThan(200);
    renderBlock({ url: HUGE_URL });
    const link = declared();
    expect(link, "有地址就要显示这一行").not.toBeNull();
    expect(link!.getAttribute("href")).toBe(HUGE_URL);
    expect(link!.getAttribute("target")).toBe("_blank");
    expect(link!.getAttribute("rel")).toContain("noopener");
    //: 全文一直在页面上(不是截断 + 悬停才给),就在这个链接**自己的容器里**
    expect(link!.textContent?.trim()).toBe(HUGE_URL);
    const text = within(link!).getByText(HUGE_URL);
    expect(text.textContent).toBe(HUGE_URL);
    //: 超长地址不撑破:任意处可断行;不是省略号截断
    expect(text.className, "长地址要折行:break-all").toContain("break-all");
    expect(text.className, "不能再用省略号一下截掉").not.toMatch(/(?:^|\s)truncate(?=\s|$)/);
    //: 位置在「下载」那一行的**下面**(同一个块里),不是飘在画布上的浮层
    expect(link!.previousElementSibling?.textContent, "地址排在那一行下面").toContain("工作流里写着它的下载地址");
    expect(link!.closest("[data-radix-popper-content-wrapper]"), "不是 portal 里的浮层").toBeNull();
    //: 不用原生 title;也不手写绝对定位(那样会飘到画布上)
    expect(link!.getAttribute("title")).toBeNull();
    expect(link!.querySelectorAll("[title]")).toHaveLength(0);
    for (const node of [link!, ...link!.querySelectorAll<HTMLElement>("*")]) {
      expect(node.getAttribute("class") ?? "", "不手写 absolute/fixed").not.toMatch(/(?:^|\s)(?:absolute|fixed)(?=\s|$)/);
      expect(node.getAttribute("style") ?? "").not.toMatch(/position\s*:/);
    }
  });

  it("套上 ComfyWorkbench 那一列(说明默认朝左):悬停也不冒浮层,全文不在浮层里", () => {
    //: Radix 的第一次悬停走 `setTimeout(delayDuration)`(假计时器推过去),才看得出旧实现会弹什么
    vi.useFakeTimers();
    try {
      renderBlock({ url: HUGE_URL });
      const link = declared()!;
      const text = within(link).getByText(HUGE_URL);
      //: 旧实现是 Truncate:强行让它「被截断」,悬停就会在左边弹出长浮层(桌面版还会画到原生视图上面)
      Object.defineProperty(text, "scrollWidth", { value: 900, configurable: true });
      Object.defineProperty(text, "clientWidth", { value: 260, configurable: true });
      fireEvent.pointerEnter(text);
      fireEvent.pointerMove(text);
      act(() => {
        vi.runOnlyPendingTimers();
      });
      expect(document.querySelector("[data-tooltip]"), "完整地址常显在下面,不该再靠朝左的浮层").toBeNull();
      expect(screen.queryByRole("tooltip")).toBeNull();
      expect(document.querySelector("[data-truncate-full]")).toBeNull();
      expect(link.textContent?.trim()).toBe(HUGE_URL);
    } finally {
      vi.useRealTimers();
    }
  });

  it("没有声明地址:不显示这一行(不摆空占位)", async () => {
    renderBlock({ url: "" });
    expect(declared()).toBeNull();
    expect(screen.getByRole("button", { name: /找「/ })).toBeTruthy();
  });
});

// --- 二、多平台:只有确认是同一个文件的才给 ------------------------------------------

const ALTERNATE = {
  source: "huggingface",
  repo: "Comfy-Org/flux1-dev",
  title: "Comfy-Org/flux1-dev",
  filename: NAME,
  url: "https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors",
  page: "https://huggingface.co/Comfy-Org/flux1-dev/blob/main/flux1-dev-fp8.safetensors",
  size: 17_246_524_772,
  base_model: "",
  exact: true,
  confidence: "confirmed",
  direct: true,
  sha256: DIGEST,
};

describe("多平台下载", () => {
  it("工作流声明的 SHA256 和平台元数据一致:该来源出现在可选里;下载走它,并把 SHA256 交给下载去核对", async () => {
    api.searchModelSources.mockResolvedValue({
      filename: NAME,
      candidates: [
        //: 原来的那个地址自己不再列一遍
        { ...ALTERNATE, source: "civitai", url: "https://civitai.com/api/download/models/7", page: "https://civitai.com/models/1" },
        //: 同名但没有哈希确认的:不列(不许拿相近的冒充)
        { ...ALTERNATE, source: "modelscope", confidence: "exact", direct: false, sha256: "",
          url: "https://modelscope.cn/models/acme/flux/resolve/master/flux1-dev-fp8.safetensors" },
        //: 连「平台说 confirmed」都不可全信:它给的 SHA256 和工作流声明的不是一个,还是同一个文件名 —— 不列
        { ...ALTERNATE, source: "modelscope", sha256: "cd".repeat(32),
          url: "https://modelscope.cn/models/acme/flux/resolve/master/flux1-dev-fp8.safetensors" },
        ALTERNATE,
      ],
      failed: [],
      hash: { state: "matched", sha256: DIGEST, note: "哈希对上了" },
    });
    api.resolveModelLink.mockResolvedValue({ source: "huggingface", url: ALTERNATE.url, filename: NAME, exists: false,
                                             uses_token: false, note: "" });
    renderBlock({ url: "https://civitai.com/api/download/models/7", hash: DIGEST, hashType: "sha256" });
    await waitFor(() => expect(api.searchModelSources).toHaveBeenCalledWith("i1", NAME, FOLDER, DIGEST, "sha256"));
    const other = await waitFor(() => {
      const found = document.querySelector<HTMLElement>("[data-alternate-source]");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(other.getAttribute("data-alternate-source")).toBe("huggingface");
    expect(other.textContent).toContain("Comfy-Org/flux1-dev");
    const page = other.querySelector<HTMLAnchorElement>("a[data-alternate-page]");
    expect(page?.getAttribute("href")).toBe(ALTERNATE.page);
    expect(document.querySelectorAll("[data-alternate-source]"), "没确认的、原地址都不列").toHaveLength(1);

    fireEvent.click(within(other).getByRole("button"));
    await waitFor(() => expect(api.resolveModelLink).toHaveBeenCalledWith("i1", ALTERNATE.url));
    const confirm = await screen.findByRole("group");
    expect(confirm.querySelector("[data-download-verified]"), "确认里写明下完还会核对").not.toBeNull();
    fireEvent.click(within(confirm).getByRole("button", { name: "开始下载" }));
    await waitFor(() => expect(api.startModelDownload).toHaveBeenCalledWith("i1", {
      workspace_id: "w1", url: ALTERNATE.url, folder: FOLDER, filename: NAME, sha256: DIGEST,
    }));
  });

  it("没有 SHA256、也没有该平台的明确 id:不查、不列(不许猜)", async () => {
    renderBlock({ url: "https://civitai.com/api/download/models/7" });
    //: 等模型库(下载走哪条路)读回来 —— 那时该发生的查询早发生了;仍然一次都没查
    await waitFor(() => expect(api.getModelLibrary).toHaveBeenCalled());
    expect(api.searchModelSources, "没有能确认的凭据就不去查").not.toHaveBeenCalled();
    expect(document.querySelector("[data-alternate-source]")).toBeNull();
    expect(declared()!.getAttribute("href")).toBe("https://civitai.com/api/download/models/7");
  });

  it("不是 SHA256 的哈希(md5 等)不算确认凭据:不查、不列", async () => {
    renderBlock({ url: "https://civitai.com/api/download/models/7", hash: "d41d8cd98f00b204e9800998ecf8427e", hashType: "md5" });
    await waitFor(() => expect(api.getModelLibrary).toHaveBeenCalled());
    expect(api.searchModelSources).not.toHaveBeenCalled();
    expect(document.querySelector("[data-alternate-source]")).toBeNull();
  });

  it("离线:多平台整个不出现(不查、也不拿旧候选骗人);原来那个地址还在", async () => {
    onlineManager.setOnline(false);
    try {
      renderBlock({ url: "https://civitai.com/api/download/models/7", hash: DIGEST, hashType: "sha256" });
      await waitFor(() => expect(declared()).not.toBeNull());
      expect(api.searchModelSources, "离线不去问平台").not.toHaveBeenCalled();
      expect(document.querySelector("[data-other-sources]")).toBeNull();
      expect(declared()!.getAttribute("href")).toBe("https://civitai.com/api/download/models/7");
    } finally {
      cleanup();
      onlineManager.setOnline(true);
    }
  });

  it("平台查询失败 / 超时:只剩原来那个地址,仍然能下(查询失败不拖着下载一起坏)", async () => {
    api.searchModelSources.mockRejectedValue(new Error("timeout"));
    api.resolveModelLink.mockResolvedValue({ source: "civitai", url: "https://civitai.com/api/download/models/7",
                                             filename: NAME, exists: false, uses_token: false, note: "" });
    renderBlock({ url: "https://civitai.com/api/download/models/7", hash: DIGEST, hashType: "sha256" });
    await waitFor(() => expect(api.searchModelSources).toHaveBeenCalled());
    expect(document.querySelector("[data-alternate-source]")).toBeNull();
    expect(document.querySelector("[role=alert]"), "查询失败不吵用户:多平台不出现就够了").toBeNull();
    const download = screen.getByRole("button", { name: `下载 ${NAME}` });
    fireEvent.click(download);
    await waitFor(() => expect(api.resolveModelLink).toHaveBeenCalledWith("i1", "https://civitai.com/api/download/models/7"));
    const confirm = await screen.findByRole("group");
    fireEvent.click(within(confirm).getByRole("button", { name: "开始下载" }));
    await waitFor(() => {
      expect(api.startModelDownload, "原地址的下载不带哈希(和以前一样)").toHaveBeenCalledWith("i1", {
        workspace_id: "w1", url: "https://civitai.com/api/download/models/7", folder: FOLDER, filename: NAME,
      });
    });
  });
});

// --- 三、下载中可以取消 -------------------------------------------------------------

describe("下载中取消", () => {
  it("正在下载的那一行有「取消」;点它 -> 取消这个任务,那一行说清「已取消 + 没下完的部分已删掉」", async () => {
    api.cancelJob.mockResolvedValue({ id: "job-1", status: "cancelled", message: "" });
    await startDownload();
    const cancel = await screen.findByRole("button", { name: `取消下载 ${NAME}` });
    //: 复用仓里的 Button(基础件),不是原生 <button>:原生按钮进不了 design/nativeButtons 那一套
    expect(cancel.tagName).toBe("BUTTON");
    expect(cancel.className, "仓里 Button 的样子").toContain("inline-flex");
    fireEvent.click(cancel);
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalledWith("job-1"));
    const said = await screen.findByText(/已取消/);
    expect(said.textContent).toContain("没下完的部分已删掉");
    expect(screen.queryByRole("button", { name: `取消下载 ${NAME}` }), "取消了就不该还能再点一次").toBeNull();
  });

  it("任务其实已经结束了:说「已经结束了,不用取消」,不冒充成取消失败吓人", async () => {
    let status = "running";
    api.getJob.mockImplementation(async () => ({ id: "job-1", status, message: "" }));
    api.cancelJob.mockRejectedValue(new Error("任务已结束,无法取消"));
    await startDownload();
    //: 点下去的那一刻它刚好做完(取消的请求晚到):再读一次任务,看到终态
    status = "succeeded";
    fireEvent.click(await screen.findByRole("button", { name: `取消下载 ${NAME}` }));
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalledWith("job-1"));
    expect(await screen.findByText(/已经结束了.*不用取消/), "这句话要在").toBeTruthy();
    expect(screen.queryByText(/取消失败/), "已经不是能不能取消的问题了").toBeNull();
  });

  it("取消真的没成功:说「取消失败」并带上原因,不说成任务已结束", async () => {
    api.cancelJob.mockRejectedValue(new Error("连不上后端"));
    await startDownload();
    fireEvent.click(await screen.findByRole("button", { name: `取消下载 ${NAME}` }));
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalledWith("job-1"));
    const said = await screen.findByText(/取消失败/);
    expect(said.textContent).toContain("连不上后端");
    expect(screen.queryByText(/已经结束了/), "任务还在跑,别把它说成结束了").toBeNull();
  });

  it("经 ComfyUI-Manager 下载的:取消只是不再等,那台机器上的下载还会继续 —— 不说「已删掉」", async () => {
    api.cancelJob.mockResolvedValue({ id: "job-1", status: "cancelled", message: "" });
    await startDownload("manager");
    fireEvent.click(await screen.findByRole("button", { name: `取消下载 ${NAME}` }));
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalledWith("job-1"));
    const said = await screen.findByText(/已取消/);
    expect(said.textContent, "那台机器自己在下,Mosael 删不了它的半截").toContain("还会继续");
    expect(said.textContent).not.toContain("已删掉");
  });
});
