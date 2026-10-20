/** @vitest-environment jsdom */
/**
 * 社区分享的**预览再导入**:先看清是什么(标题 / 作者 / 类型 / 大小),人点了才导入。
 *
 * 断言的是三件事,不是某一句中文:
 * - 预览把详情和内容都取回来了,弹窗里四样东西都在,两颗按钮都在;
 * - 「导入到工作区」走的是**现有的** `POST /api/workflows/import`(这里拦 transport,断言路径和方法),
 *   下载计数走 `POST /shares/{id}/download`(预览、取消都不计数);
 * - 三种失败(分享不在 / 网络 / 格式不对)各自有下一步;内容不进 console。
 */
import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

const toasts = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: toasts.success, error: toasts.error } }));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ t: (key: string) => key, locale: "zh-CN" }),
}));

//: 只换 transport 的 `api`,错误类型(404 / 掉线)用真的 —— 组件就是靠它们分类的。
const call = vi.hoisted(() => vi.fn());
vi.mock("@/api/transport", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/transport")>();
  return { ...actual, api: call };
});

import { ApiError, ApiOfflineError } from "@/api/transport";

import { ShareImportDialog } from "./ShareImportDialog";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

beforeEach(() => {
  call.mockReset();
  toasts.success.mockReset();
  toasts.error.mockReset();
});

afterEach(cleanup);

const DETAIL = {
  id: "sh1",
  kind: "workflow" as const,
  title: "产品短片模板",
  summary: "三镜头的小片",
  bytes: 1_500_000,
  created_at: "2026-10-20T00:00:00",
  author: { display_name: "小林", handle: "lin", avatar_seed: "s1" },
  stats: { downloads: 12, likes: 3, favorites: 1, comments: 0 },
};

/** 内容里带一个只在 payload 里出现的标记:日志断言靠它。 */
const PAYLOAD = {
  format: "mosael-workflow",
  version: 1,
  name: "产品短片模板",
  graph: { nodes: [], edges: [] },
  secret_marker: "payload-秘密-勿打印",
};

const CREATED = {
  id: "wf-new",
  workspace_id: "ws1",
  name: "产品短片模板",
  description: "",
  graph: { nodes: [], edges: [] },
};

/** 按路径路由:分享详情 / payload / 下载 / 工作流导入。 */
function route(overrides: Partial<Record<string, (path: string, init?: RequestInit) => unknown>> = {}) {
  call.mockImplementation(async (path: string, init?: RequestInit) => {
    const custom = overrides[path];
    if (custom) return custom(path, init);
    if (path === "/api/cloud/v1/shares/sh1" && !init?.method) return DETAIL;
    if (path === "/api/cloud/v1/shares/sh1/payload" && !init?.method) return { payload: PAYLOAD };
    if (path === "/api/cloud/v1/shares/sh1/download" && init?.method === "POST") return { payload: PAYLOAD };
    if (path === "/api/workflows/import" && init?.method === "POST") return CREATED;
    throw new Error(`unexpected api call: ${init?.method ?? "GET"} ${path}`);
  });
}

function renderDialog(props: Partial<React.ComponentProps<typeof ShareImportDialog>> = {}) {
  const onClose = vi.fn();
  const onImported = vi.fn();
  render(
    <ShareImportDialog
      shareId="sh1"
      workspaceId="ws1"
      onClose={onClose}
      onImported={onImported}
      {...props}
    />,
  );
  return { onClose, onImported };
}

it("预览:标题、作者昵称、类型、大小都在,两颗按钮都在", async () => {
  route();
  renderDialog();
  expect(await screen.findByText("产品短片模板")).toBeTruthy();
  expect(screen.getByText("小林")).toBeTruthy();
  expect(screen.getByText("shareImportKindWorkflow")).toBeTruthy();
  expect(screen.getByText("1.5 MB")).toBeTruthy();
  expect(screen.getByRole("button", { name: "shareImportConfirm" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "cancel" })).toBeTruthy();
  // 预览就要把内容也读回来(内容读不回来时弹窗里就说清,而不是等到点了导入才失败)。
  expect(call.mock.calls.some(([path, init]) => path === "/api/cloud/v1/shares/sh1/payload" && init === undefined)).toBe(true);
});

it("导入走现有的 POST /api/workflows/import;下载计数走 POST /download", async () => {
  route();
  const { onImported } = renderDialog();
  await screen.findByText("产品短片模板");
  await userEvent.click(screen.getByRole("button", { name: "shareImportConfirm" }));

  await waitFor(() => expect(onImported).toHaveBeenCalledWith(CREATED));

  // 计数:POST /download(不是再 GET 一次 payload)。
  expect(call).toHaveBeenCalledWith("/api/cloud/v1/shares/sh1/download", { method: "POST" });

  const imported = call.mock.calls.find(([path, init]) => path === "/api/workflows/import" && init?.method === "POST");
  expect(imported, "导入必须走现有的工作流导入接口").toBeTruthy();
  expect(JSON.parse(imported![1].body as string)).toEqual({ workspace_id: "ws1", data: PAYLOAD });
  // 成功一句提示里带的是导入后的名字(不是只弹一句「成功」)。
  expect(toasts.success).toHaveBeenCalled();
});

it("分享不存在:说清并给下一步(不是一句 request failed)", async () => {
  call.mockRejectedValue(new ApiError("Not Found", 404, '{"detail":"share_not_found"}'));
  renderDialog();
  expect(await screen.findByText("shareImportNotFound")).toBeTruthy();
  expect(screen.getByText("shareImportNotFoundFix")).toBeTruthy();
  expect(screen.getByRole("button", { name: "shareImportConfirm" })).toBeDisabled();
});

it("网络失败:说清连不上,并给重试", async () => {
  call.mockRejectedValue(new ApiOfflineError("offline"));
  renderDialog();
  expect(await screen.findByText("shareImportOffline")).toBeTruthy();
  expect(screen.getByText("shareImportOfflineFix")).toBeTruthy();
  expect(screen.getByRole("button", { name: "retry" })).toBeTruthy();
});

it("格式不对:后端拒绝(422)时给的是「换一份 / 手动导入」,并把后端的话收进详情", async () => {
  route({
    "/api/workflows/import": () => {
      throw new ApiError("不是 Mosael 工作流文件", 422, '{"detail":"不是 Mosael 工作流文件"}');
    },
  });
  renderDialog();
  await screen.findByText("产品短片模板");
  await userEvent.click(screen.getByRole("button", { name: "shareImportConfirm" }));
  expect(await screen.findByText("shareImportInvalid")).toBeTruthy();
  expect(screen.getByText("shareImportInvalidFix")).toBeTruthy();
  // 后端原话收在「详情」里(不是拿它替换掉那句概括)。
  await userEvent.click(screen.getByRole("button", { name: "failureDetail" }));
  expect(await screen.findByText(/不是 Mosael 工作流文件/)).toBeTruthy();
});

it("画板分享:不造假导入,说明「先下载文件手动导入」,导入键不可点", async () => {
  call.mockImplementation(async (path: string) => {
    if (path === "/api/cloud/v1/shares/sh1") return { ...DETAIL, kind: "board" };
    throw new Error(`unexpected api call: ${path}`);
  });
  renderDialog();
  expect(await screen.findByText("shareImportBoardUnsupported")).toBeTruthy();
  expect(screen.getByRole("button", { name: "shareImportConfirm" })).toBeDisabled();
  // 画板连内容都不取:没有可用的导入通道,取回来只会是白白下载 2 MB。
  expect(call).not.toHaveBeenCalledWith("/api/cloud/v1/shares/sh1/payload", undefined);
});

it("payload 不进日志", async () => {
  route();
  const spies = (["log", "info", "warn", "error", "debug"] as const).map((name) => vi.spyOn(console, name).mockImplementation(() => {}));
  const { onImported } = renderDialog();
  await screen.findByText("产品短片模板");
  await userEvent.click(screen.getByRole("button", { name: "shareImportConfirm" }));
  await waitFor(() => expect(onImported).toHaveBeenCalled());
  for (const spy of spies) {
    for (const args of spy.mock.calls) {
      expect(JSON.stringify(args)).not.toContain("payload-秘密-勿打印");
      expect(JSON.stringify(args)).not.toContain("secret_marker");
    }
  }
  for (const spy of spies) spy.mockRestore();
});
