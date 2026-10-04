/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 网页里点的下载:不弹保存框,主进程下好了告诉渲染层,渲染层用自己的服务器和会话存进当前工作区。
 * 主进程换成假的 window.mosaelPageTools(能手动推一条下载通知),要验的是「交给主进程去存的是什么」,
 * 以及提示说在哪儿:顶栏挂着说在顶栏里(网页盖住了窗口其余部分),没挂着用应用的 toast。
 */

const WITH_PLACEHOLDER: Record<string, string> = {
  browserToolsFileDownloading: "downloading {name} {p}%",
  browserToolsFileDownloadingUnknown: "downloading {name}",
  browserToolsFileSaving: "saving {name}",
  browserToolsFileSaved: "saved {name}",
  browserToolsFileNoWorkspace: "no workspace for {name}",
  browserToolsDownloadFailed: "failed: {reason}",
};
const t = (key: string) => WITH_PLACEHOLDER[key] ?? key;
vi.mock("@/app/preferences", () => ({ useI18n: () => t, usePreferences: () => ({ locale: "zh-CN" }) }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), loading: vi.fn(), dismiss: vi.fn() }));
vi.mock("sonner", () => ({ toast }));
vi.mock("@/api/transport", () => ({ API_BASE: "http://127.0.0.1:8800", getAuthToken: () => "tok" }));
vi.mock("@/api/client", () => ({ listBrowserProfiles: vi.fn(async () => []) }));
const links = vi.hoisted(() => ({ gotoRecord: vi.fn(), emitOpenEvent: vi.fn(), openNote: vi.fn() }));
vi.mock("@/lib/deepLink", () => links);

const { BrowserDownloads } = await import("./BrowserDownloads");
const { BrowserSessionTools } = await import("./BrowserSessionTools");
const { BrowserToolsWorkspace } = await import("@/app/browserToolsWorkspace");

type Notice = Parameters<Parameters<NonNullable<Window["mosaelPageTools"]>["onDownload"]>[0]>[0];

let push: (notice: Notice) => void;
let saveDownload: ReturnType<typeof vi.fn>;
const hideView = vi.fn();

beforeEach(() => {
  for (const fn of [...Object.values(toast), ...Object.values(links), hideView]) fn.mockReset();
  saveDownload = vi.fn(async () => ({ id: "asset-9", name: "report.pdf", kind: "document" }));
  const tools = {
    onDownload: vi.fn((callback: (notice: Notice) => void) => {
      push = callback;
      return () => undefined;
    }),
    saveDownload,
    setInset: vi.fn(async () => undefined),
  };
  Object.assign(window, { mosaelPageTools: tools, mosaelPublish: { hideView } });
});

function show({ workspaceId = "ws" as string | null, toolbar = false } = {}) {
  const client = new QueryClient();
  const state: PublishViewState = { visible: true, accountId: "persist:pool-p1", accountName: "档案", url: "https://example.com/" };
  return render(
    <QueryClientProvider client={client}>
      <BrowserToolsWorkspace.Provider value={{ workspaceId, setWorkspaceId: () => undefined }}>
        <BrowserDownloads />
        {toolbar && workspaceId && <BrowserSessionTools workspaceId={workspaceId} state={state} barHeight={56} />}
      </BrowserToolsWorkspace.Provider>
    </QueryClientProvider>,
  );
}

const ready = (extra: Partial<Notice> = {}): Notice => ({
  id: "0f8fad5b-d9cb-469f-a165-70867728950e",
  name: "report.pdf",
  state: "ready",
  receivedBytes: 3,
  totalBytes: 3,
  ...extra,
});

describe("网页里点的下载存进素材库", () => {
  it("下好了就用界面自己的服务器、会话和当前工作区去存;存好了说一句,点「查看」跳到那一份", async () => {
    show();
    act(() => push(ready()));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(saveDownload).toHaveBeenCalledWith({
      id: "0f8fad5b-d9cb-469f-a165-70867728950e",
      server: "http://127.0.0.1:8800",
      token: "tok",
      workspaceId: "ws",
      projectId: null,
    });
    const [text, options] = toast.success.mock.calls[0];
    expect(text).toBe("saved report.pdf");
    options.action.onClick();
    expect(hideView).toHaveBeenCalled();
    expect(links.gotoRecord).toHaveBeenCalledWith("/media", "mosael:open-asset", "asset-9");
  });

  it("下载中带百分比,同一份下载的提示原地更新(同一个 toast id)", () => {
    show();
    act(() => push(ready({ state: "progress", receivedBytes: 50, totalBytes: 200 })));
    expect(toast.loading).toHaveBeenCalledWith("downloading report.pdf 25%", { id: ready().id });
    act(() => push(ready({ state: "progress", receivedBytes: 10, totalBytes: 0 })));
    expect(toast.loading).toHaveBeenLastCalledWith("downloading report.pdf", { id: ready().id });
  });

  it("没下成(类型不收、太大):照主进程那句话说", () => {
    show();
    act(() => push(ready({ state: "failed", error: "素材库不收这种文件:「setup.exe」" })));
    expect(toast.error).toHaveBeenCalledWith("failed: 素材库不收这种文件:「setup.exe」", { id: ready().id });
    expect(saveDownload).not.toHaveBeenCalled();
  });

  it("后端拒收:说那句话", async () => {
    saveDownload.mockRejectedValueOnce(new Error("「report.pdf」下载好了,但没能存进素材库:文件太大"));
    show();
    act(() => push(ready()));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.error.mock.calls[0][0]).toContain("没能存进素材库");
  });

  it("还没进工作区:不存,说没地方存", async () => {
    show({ workspaceId: null });
    act(() => push(ready()));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(saveDownload).not.toHaveBeenCalled();
    expect(toast.error.mock.calls[0][0]).toBe("no workspace for report.pdf");
  });

  it("内嵌浏览器亮着(顶栏工具区挂着):提示说在顶栏里,不弹 toast", async () => {
    show({ toolbar: true });
    act(() => push(ready()));
    await waitFor(() => expect(document.querySelector("[data-page-tools-notice]")?.textContent).toContain("saved report.pdf"));
    expect(toast.success).not.toHaveBeenCalled();
    fireEvent.click(document.querySelector("[data-page-tools-notice] button") as HTMLElement);
    expect(links.gotoRecord).toHaveBeenCalledWith("/media", "mosael:open-asset", "asset-9");
  });
});
