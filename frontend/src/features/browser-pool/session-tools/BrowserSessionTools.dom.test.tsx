/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

/**
 * 浏览器会话顶栏的页面工具,走的都是用户会点的那几下:截屏三种、下载视频(平台页 / 直链 / 受保护 / 没有)、
 * 采集图片、存成笔记、用当前页开工、交给智能体。主进程那一侧换成假的 window.mosaelPageTools,后端接口换成
 * 记账的假货 —— 要验的是「交给后端的是什么」:出处、档案、走哪条路。
 */

// 带占位符的几条把占位符留着,才看得出拼进去的是什么(原因、像素……)。
const WITH_PLACEHOLDER: Record<string, string> = {
  browserToolsFailed: "browserToolsFailed:{reason}",
  browserToolsDownloadFailed: "browserToolsDownloadFailed:{reason}",
  browserToolsTruncated: "browserToolsTruncated:{px}",
};
const t = (key: string) => WITH_PLACEHOLDER[key] ?? key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t, usePreferences: () => ({ locale: "zh-CN" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const api = vi.hoisted(() => ({
  listBrowserProfiles: vi.fn(),
  importWebCapture: vi.fn(),
  importFromUrl: vi.fn(),
  urlSupport: vi.fn(),
  getJob: vi.fn(),
  cancelJob: vi.fn(),
  createNoteFromPage: vi.fn(),
  startWorkflowFromPage: vi.fn(),
}));
vi.mock("@/api/client", () => api);

const agent = vi.hoisted(() => ({ startNewAgentSession: vi.fn(), AGENT_DRAFT_EVENT: "mosael:agent-draft" }));
vi.mock("@/features/agent/currentAgentSession", () => agent);

const links = vi.hoisted(() => ({ gotoRecord: vi.fn(), emitOpenEvent: vi.fn(), openNote: vi.fn() }));
vi.mock("@/lib/deepLink", () => links);

const { BrowserSessionTools } = await import("./BrowserSessionTools");

const PAGE = { url: "https://example.com/post/1", title: "一篇帖子" };
const STATE: PublishViewState = {
  visible: true,
  accountId: "persist:pool-p1",
  accountName: "我的档案",
  url: PAGE.url,
  title: PAGE.title,
  partition: "persist:pool-p1",
};
const PNG = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function capture(extra: Record<string, unknown> = {}) {
  return { bytes: PNG, width: 2560, height: 1600, truncated: false, page: PAGE, capturedAt: "2026-10-04T05:30:00.000Z", ...extra };
}

let tools: Record<string, ReturnType<typeof vi.fn>>;
const hideView = vi.fn();

beforeEach(() => {
  for (const fn of [...Object.values(api), ...Object.values(links), agent.startNewAgentSession, hideView]) fn.mockReset();
  api.listBrowserProfiles.mockResolvedValue([{ id: "p1", partition: "persist:pool-p1", name: "我的档案" }]);
  api.importWebCapture.mockImplementation(async () => ({ id: "asset-1" }));
  api.urlSupport.mockResolvedValue({ supported: false, extractor: "" });
  tools = {
    capture: vi.fn(async (mode: string) => capture(mode === "full" ? { truncated: true } : {})),
    beginRegion: vi.fn(async () => ({ frame: "data:image/png;base64,AAAA", width: 2000, height: 1000 })),
    finishRegion: vi.fn(async (selection: unknown) => (selection ? capture({ width: 1000, height: 500 }) : null)),
    probeVideos: vi.fn(async () => ({ page: PAGE, candidates: [], drm: false, streamOnly: false })),
    listImages: vi.fn(async () => ({ page: PAGE, images: [] })),
    fetchImages: vi.fn(async () => []),
    readPage: vi.fn(async (mode: string) => ({ page: PAGE, html: mode === "article" ? "<article>正文</article>" : "", selection: "" })),
    setInset: vi.fn(async () => undefined),
  };
  Object.assign(window, { mosaelPageTools: tools, mosaelPublish: { hideView } });
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
});

function show(state: PublishViewState = STATE) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BrowserSessionTools workspaceId="ws" state={state} barHeight={56} />
    </QueryClientProvider>,
  );
}

const toolButton = (key: string) => document.querySelector(`[data-page-tool="${key}"]`) as HTMLElement;
const choiceButton = (key: string) => document.querySelector(`[data-page-choice="${key}"]`) as HTMLElement;
const notice = () => document.querySelector("[data-page-tools-notice]") as HTMLElement | null;

describe("截屏到素材", () => {
  it("可见区域:截下来带着出处入库,顶栏说「已存进素材库」,点「查看」跳到那一份", async () => {
    show();
    fireEvent.click(toolButton("shot"));
    fireEvent.click(choiceButton("visible"));
    await waitFor(() => expect(api.importWebCapture).toHaveBeenCalled());
    expect(tools.capture).toHaveBeenCalledWith("visible");
    const sent = api.importWebCapture.mock.calls[0][0];
    expect(sent).toMatchObject({
      workspaceId: "ws",
      capture: "screenshot_visible",
      pageUrl: PAGE.url,
      pageTitle: PAGE.title,
      capturedAt: "2026-10-04T05:30:00.000Z",
      name: "一篇帖子 · browserToolsShotNameVisible",
    });
    expect(sent.file).toBeInstanceOf(Blob);
    expect(sent.file.type).toBe("image/png");
    expect(sent.sourceUrl).toBeUndefined();
    await waitFor(() => expect(notice()).toHaveTextContent("browserToolsSavedAsset"));
    fireEvent.click(within(notice()!).getByText("browserToolsView"));
    expect(hideView).toHaveBeenCalled();
    expect(links.gotoRecord).toHaveBeenCalledWith("/media", "mosael:open-asset", "asset-1");
  });

  it("整页长图:超长页面截了一段时如实说", async () => {
    show();
    fireEvent.click(toolButton("shot"));
    fireEvent.click(choiceButton("full"));
    await waitFor(() => expect(notice()).toHaveTextContent("browserToolsTruncated:15000"));
    expect(api.importWebCapture.mock.calls[0][0].capture).toBe("screenshot_full");
  });

  it("整页长图截不了时说清原因,不报一串英文", async () => {
    tools.capture.mockRejectedValueOnce(new Error("Error invoking remote method 'pageTools:capture': PageToolError: page-tools: full_page_unavailable"));
    show();
    fireEvent.click(toolButton("shot"));
    fireEvent.click(choiceButton("full"));
    await waitFor(() => expect(notice()).toHaveTextContent("browserToolsFullPageUnavailable"));
    expect(api.importWebCapture).not.toHaveBeenCalled();
  });

  it("框选:冻结画面上拖出来的框按比例交给主进程,裁出来的那块入库", async () => {
    show();
    fireEvent.click(toolButton("shot"));
    fireEvent.click(choiceButton("region"));
    const overlay = await waitFor(() => {
      const found = document.querySelector("[data-region-overlay]") as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    const image = overlay.querySelector("img")!;
    image.getBoundingClientRect = () => ({ left: 0, top: 56, width: 1000, height: 500, right: 1000, bottom: 556, x: 0, y: 56, toJSON: () => ({}) });
    fireEvent.pointerDown(overlay, { clientX: 100, clientY: 106, pointerId: 1 });
    fireEvent.pointerMove(overlay, { clientX: 600, clientY: 306, pointerId: 1 });
    fireEvent.pointerUp(overlay, { clientX: 600, clientY: 306, pointerId: 1 });
    await waitFor(() => expect(api.importWebCapture).toHaveBeenCalled());
    expect(tools.finishRegion).toHaveBeenCalledWith({ x: 0.1, y: 0.1, width: 0.5, height: 0.4 });
    expect(api.importWebCapture.mock.calls[0][0].capture).toBe("screenshot_region");
    expect(document.querySelector("[data-region-overlay]")).toBeNull();
  });

  it("框选按 Esc 取消:网页亮回来,什么都不存", async () => {
    show();
    fireEvent.click(toolButton("shot"));
    fireEvent.click(choiceButton("region"));
    await waitFor(() => expect(document.querySelector("[data-region-overlay]")).not.toBeNull());
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(tools.finishRegion).toHaveBeenCalledWith(null));
    expect(api.importWebCapture).not.toHaveBeenCalled();
  });
});

describe("下载页面里的视频", () => {
  it("平台页面:按整页走「从链接导入」,带当前档案;侧栏开着时网页让出右边", async () => {
    api.urlSupport.mockResolvedValue({ supported: true, extractor: "BiliBili" });
    api.importFromUrl.mockResolvedValue({ id: "job-1", progress: 0 });
    show();
    fireEvent.click(toolButton("video"));
    expect(tools.setInset).toHaveBeenCalledWith(360);
    const card = await waitFor(() => {
      const found = document.querySelector("[data-video-platform]") as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    fireEvent.click(within(card).getByRole("button"));
    await waitFor(() => expect(api.importFromUrl).toHaveBeenCalled());
    expect(api.importFromUrl.mock.calls[0][0]).toEqual({
      workspace_id: "ws",
      items: [{ url: PAGE.url, title: PAGE.title, page_url: PAGE.url, page_title: PAGE.title }],
      kind: "video",
      max_height: 0,
      profile_id: "p1",
    });
  });

  it("直链:下那条地址,带着所在页面;进度跑完说「已存进素材库」", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    tools.probeVideos.mockResolvedValue({
      page: PAGE,
      drm: false,
      streamOnly: false,
      candidates: [{ url: "https://cdn.example.com/a.mp4", kind: "direct", from: "element", mime: "video/mp4", bytes: 1024, width: 1280, height: 720, duration: 12, protection: null }],
    });
    api.importFromUrl.mockResolvedValue({ id: "job-2", progress: 0 });
    api.getJob.mockResolvedValue({ id: "job-2", status: "succeeded", progress: 1, result: { asset_ids: ["asset-9"] }, error: null });
    show();
    fireEvent.click(toolButton("video"));
    const row = await waitFor(() => {
      const found = document.querySelector('[data-video-candidate="direct"]') as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    fireEvent.click(within(row).getByRole("button"));
    await waitFor(() => expect(api.importFromUrl).toHaveBeenCalled());
    expect(api.importFromUrl.mock.calls[0][0].items).toEqual([
      { url: "https://cdn.example.com/a.mp4", title: PAGE.title, page_url: PAGE.url, page_title: PAGE.title },
    ]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    await waitFor(() => expect(notice()).toHaveTextContent("browserToolsSavedAsset"));
    fireEvent.click(within(notice()!).getByText("browserToolsView"));
    expect(links.gotoRecord).toHaveBeenCalledWith("/media", "mosael:open-asset", "asset-9");
  });

  it("受保护(加密流 / DRM):如实说「受保护,无法下载」,不给下载按钮", async () => {
    tools.probeVideos.mockResolvedValue({
      page: PAGE,
      drm: true,
      streamOnly: false,
      candidates: [{ url: "https://cdn.example.com/locked/index.m3u8", kind: "hls", from: "element", mime: "", bytes: null, width: 0, height: 0, duration: null, protection: "encrypted" }],
    });
    show();
    fireEvent.click(toolButton("video"));
    const row = await waitFor(() => {
      const found = document.querySelector('[data-video-candidate="hls"]') as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    expect(within(row).getByText("browserToolsVideoProtected")).toBeInTheDocument();
    expect(within(row).queryByRole("button")).toBeNull();
    expect(document.querySelector("[data-video-drm]")).toHaveTextContent("browserToolsVideoDrmBanner");
  });

  it("没有视频:说没找到", async () => {
    show();
    fireEvent.click(toolButton("video"));
    await waitFor(() => expect(document.querySelector("[data-video-empty]")).toHaveTextContent("browserToolsVideoEmpty"));
  });

  it("下载可以取消", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    tools.probeVideos.mockResolvedValue({
      page: PAGE,
      drm: false,
      streamOnly: false,
      candidates: [{ url: "https://cdn.example.com/a.mp4", kind: "direct", from: "network", mime: "video/mp4", bytes: null, width: 0, height: 0, duration: null, protection: null }],
    });
    api.importFromUrl.mockResolvedValue({ id: "job-3", progress: 0 });
    api.getJob.mockResolvedValue({ id: "job-3", status: "running", progress: 0.4, result: null, error: null });
    api.cancelJob.mockResolvedValue({ id: "job-3", status: "failed" });
    show();
    fireEvent.click(toolButton("video"));
    const row = await waitFor(() => {
      const found = document.querySelector('[data-video-candidate="direct"]') as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    fireEvent.click(within(row).getByRole("button"));
    const running = await waitFor(() => {
      const found = document.querySelector('[data-download-status="running"]') as HTMLElement | null;
      expect(found).not.toBeNull();
      return found!;
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    fireEvent.click(within(running).getByRole("button", { name: "browserToolsDownloadCancel" }));
    await waitFor(() => expect(api.cancelJob).toHaveBeenCalledWith("job-3"));
    await waitFor(() => expect(document.querySelector('[data-download-status="cancelled"]')).not.toBeNull());
  });
});

describe("采集页面图片", () => {
  it("取到的才能勾;勾中的带着页面与图片地址一张张入库", async () => {
    tools.listImages.mockResolvedValue({
      page: PAGE,
      images: [
        { url: "https://cdn.example.com/a.jpg", width: 800, height: 600, alt: "大图" },
        { url: "https://cdn.example.com/b.jpg", width: 800, height: 600, alt: "" },
      ],
    });
    tools.fetchImages.mockResolvedValue([
      { url: "https://cdn.example.com/a.jpg", ok: true, bytes: Uint8Array.from([0xff, 0xd8, 0xff]), mime: "image/jpeg" },
      { url: "https://cdn.example.com/b.jpg", ok: false, reason: "failed" },
    ]);
    show();
    fireEvent.click(toolButton("images"));
    await waitFor(() => expect(document.querySelector('[data-page-image="ready"]')).not.toBeNull());
    expect(document.querySelector('[data-page-image="failed"]')).toBeDisabled();
    fireEvent.click(document.querySelector('[data-page-image="ready"]')!);
    fireEvent.click(screen.getByRole("button", { name: /browserToolsImagesSave/ }));
    await waitFor(() => expect(api.importWebCapture).toHaveBeenCalledTimes(1));
    expect(api.importWebCapture.mock.calls[0][0]).toMatchObject({
      capture: "page_image",
      sourceUrl: "https://cdn.example.com/a.jpg",
      pageUrl: PAGE.url,
      pageTitle: PAGE.title,
      name: "大图",
    });
    expect(api.importWebCapture.mock.calls[0][0].file.type).toBe("image/jpeg");
    await waitFor(() => expect(notice()).toHaveTextContent("browserToolsSavedAsset"));
  });
});

describe("存成笔记", () => {
  it("整页正文:把渲染后的页面交给后端建笔记,点「打开」去那篇", async () => {
    api.createNoteFromPage.mockResolvedValue({ id: "note-1" });
    show();
    fireEvent.click(toolButton("note"));
    fireEvent.click(choiceButton("article"));
    await waitFor(() => expect(api.createNoteFromPage).toHaveBeenCalled());
    expect(api.createNoteFromPage.mock.calls[0][0]).toEqual({
      workspace_id: "ws", url: PAGE.url, title: PAGE.title, html: "<article>正文</article>", selection: "",
    });
    await waitFor(() => expect(notice()).toHaveTextContent("browserToolsNoteSaved"));
    fireEvent.click(within(notice()!).getByText("browserToolsOpen"));
    expect(links.openNote).toHaveBeenCalledWith("note-1");
  });

  it("选中的文字:没选中就先说一声,不建空笔记", async () => {
    show();
    fireEvent.click(toolButton("note"));
    fireEvent.click(choiceButton("selection"));
    await waitFor(() => expect(notice()).toHaveTextContent("browserToolsNoSelection"));
    expect(api.createNoteFromPage).not.toHaveBeenCalled();
  });
});

describe("用当前页开工", () => {
  it("模板:用当前页链接和当前档案建好(或打开)那张图,收起浏览器跳过去", async () => {
    api.startWorkflowFromPage.mockResolvedValue({ id: "wf-1", name: "自媒体视频爆款拆解" });
    show();
    fireEvent.click(toolButton("start"));
    fireEvent.click(choiceButton("viral_video_breakdown"));
    await waitFor(() => expect(links.gotoRecord).toHaveBeenCalledWith("/workflows", "mosael:open-workflow", "wf-1"));
    expect(api.startWorkflowFromPage).toHaveBeenCalledWith({
      workspace_id: "ws", template_id: "viral_video_breakdown", url: PAGE.url, profile_id: "p1",
    });
    expect(hideView).toHaveBeenCalled();
  });

  it("交给智能体:新开一条对话,带上链接和标题,不替他发送", async () => {
    agent.startNewAgentSession.mockResolvedValue({ id: "s-1" });
    show();
    fireEvent.click(toolButton("start"));
    fireEvent.click(choiceButton("agent"));
    await waitFor(() => expect(links.gotoRecord).toHaveBeenCalledWith("/ai"));
    expect(agent.startNewAgentSession).toHaveBeenCalledWith(expect.anything(), "ws");
    const [event, text] = links.emitOpenEvent.mock.calls[0];
    expect(event).toBe("mosael:agent-draft");
    expect(text).toContain(PAGE.url);
    expect(text).toContain(PAGE.title);
  });
});

it("选了一项就收回去,工具马上又点得到(连着截两张不用先收起)", async () => {
  show();
  fireEvent.click(toolButton("shot"));
  fireEvent.click(choiceButton("visible"));
  expect(choiceButton("visible")).toBeNull();
  await waitFor(() => expect(notice()).toHaveTextContent("browserToolsSavedAsset"));
  fireEvent.click(toolButton("shot"));
  fireEvent.click(choiceButton("full"));
  await waitFor(() => expect(api.importWebCapture).toHaveBeenCalledTimes(2));
});

it("子选项在顶栏里原地展开(不往网页上掉),Esc 收回", () => {
  show();
  fireEvent.click(toolButton("shot"));
  expect(choiceButton("visible")).not.toBeNull();
  expect(toolButton("shot")).toBeNull();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(choiceButton("visible")).toBeNull();
  expect(toolButton("shot")).not.toBeNull();
});

describe("工具区只留图标", () => {
  const TOOLS = [
    ["shot", "browserToolsShot"],
    ["video", "browserToolsVideo"],
    ["images", "browserToolsImages"],
    ["note", "browserToolsNote"],
    ["start", "browserToolsStart"],
  ] as const;

  it("按钮上没有字;名字是按钮的名字,名字和一句补充说明在悬停说明里", async () => {
    show();
    for (const [key, label] of TOOLS) {
      const button = toolButton(key);
      expect(button.textContent).toBe("");
      expect(button.getAttribute("aria-label")).toBe(label);
      expect(button.hasAttribute("title")).toBe(false);
      expect(await readHint(button)).toBe(`${label}${label}Hint`);
      act(() => button.blur());
    }
  });

  it("页面还没打开(空白页、错误页):工具都点不了,说明里写为什么", async () => {
    show({ ...STATE, url: "about:blank", title: "" });
    for (const [key] of TOOLS) expect((toolButton(key) as HTMLButtonElement).disabled).toBe(true);
    expect(await readHint(toolButton("shot"))).toContain("browserToolsNeedsPage");
  });

  it("页面还在加载:下载视频、采集图片、存成笔记等它加载完,截屏和开工照常", async () => {
    show({ ...STATE, loading: true });
    expect((toolButton("video") as HTMLButtonElement).disabled).toBe(true);
    expect((toolButton("images") as HTMLButtonElement).disabled).toBe(true);
    expect((toolButton("note") as HTMLButtonElement).disabled).toBe(true);
    expect((toolButton("shot") as HTMLButtonElement).disabled).toBe(false);
    expect((toolButton("start") as HTMLButtonElement).disabled).toBe(false);
    // 说明画在网页上面(浮层视图),不再挤在顶栏那一条里:名字、它是干什么的、为什么点不了,三样都在。
    expect(await readHint(toolButton("video"))).toBe("browserToolsVideobrowserToolsVideoHintbrowserToolsStillLoading");
  });

  it("上一个操作还没做完:工具都等一等,说明里写为什么", async () => {
    let finish: (value: unknown) => void = () => undefined;
    tools.capture.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
    show();
    fireEvent.click(toolButton("shot"));
    fireEvent.click(choiceButton("visible"));
    await waitFor(() => expect((toolButton("video") as HTMLButtonElement).disabled).toBe(true));
    expect(await readHint(toolButton("video"))).toContain("browserToolsBusy");
    await act(async () => finish(capture()));
  });
});

describe("外壳", () => {
  it("顶栏之外弹出来的侧栏也算窗口外壳(底下的弹窗不会因为点它而关掉,点得动、拿得到焦点)", async () => {
    show();
    fireEvent.click(toolButton("images"));
    const drawer = await waitFor(() => {
      const found = document.querySelector("[data-page-tools-drawer]");
      expect(found).not.toBeNull();
      return found!;
    });
    expect(drawer.closest("[data-app-chrome]")).not.toBeNull();
  });
});

describe("报错怎么说、说在哪", () => {
  it("没做成时照桌面端整理好的那句话说(不露 Electron 的原话);长的折成两行,不在地址栏旁边挤成半句", async () => {
    tools.capture.mockRejectedValueOnce(new Error("这个功能要重启 Mosael 才能用(应用的一部分还是旧版本)"));
    show();
    fireEvent.click(toolButton("shot"));
    fireEvent.click(choiceButton("visible"));
    await waitFor(() => expect(notice()?.getAttribute("data-page-tools-notice")).toBe("error"));
    expect(notice()).toHaveTextContent("browserToolsFailed:这个功能要重启 Mosael 才能用(应用的一部分还是旧版本)");
    expect(notice()?.textContent).not.toContain("Error invoking remote method");
    const text = notice()!.querySelector("[data-page-tools-notice-text]") as HTMLElement;
    expect(text.className).toContain("line-clamp-2");
  });

  it("做好了、进行中的那句话一行就够", async () => {
    show();
    fireEvent.click(toolButton("shot"));
    fireEvent.click(choiceButton("visible"));
    await waitFor(() => expect(notice()?.getAttribute("data-page-tools-notice")).toBe("done"));
    const text = notice()!.querySelector("[data-page-tools-notice-text]") as HTMLElement;
    expect(text.className).not.toContain("line-clamp-2");
  });
});

it("开发时主进程是旧的(能替你重启):报错直接给「重启」", async () => {
  const restart = vi.fn(async () => undefined);
  Object.assign(window, {
    mosaelDesktop: {
      devMain: {
        status: async () => ({ files: ["publish.bundle.cjs"], canRestart: true }),
        onStale: () => () => undefined,
        restart,
      },
    },
  });
  const { mainStale } = await import("@/features/desktop/mainStale");
  mainStale.reset();
  const off = mainStale.subscribe(() => undefined);
  await waitFor(() => expect(mainStale.get().files).toEqual(["publish.bundle.cjs"]));
  tools.capture.mockRejectedValueOnce(new Error("这个功能要重启 Mosael 才能用(应用的一部分还是旧版本)"));
  show();
  fireEvent.click(toolButton("shot"));
  fireEvent.click(choiceButton("visible"));
  await waitFor(() => expect(notice()?.getAttribute("data-page-tools-notice")).toBe("error"));
  fireEvent.click(within(notice()!).getByRole("button", { name: "mainStaleRestart" }));
  expect(restart).toHaveBeenCalled();
  off();
  mainStale.reset();
  Object.assign(window, { mosaelDesktop: undefined });
});
