/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";

/**
 * 挑素材的弹窗里**直接传一个本地文件**(用户原话:「只能从素材库里选,不能上传,这个交互非常不方便」):
 * 按钮选、拖进弹窗都行;传的是素材库同一个导入接口,看得见进度、停得下来,没传上说为什么、能再来一次;
 * 传完就当是挑中了它(弹窗由挑中的那一下关掉)。这一格要什么就只收什么 —— 图片槽拖进一段视频,就地说一句。
 */

type Upload = {
  file: File;
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
  resolve: (asset: unknown) => void;
  reject: (error: unknown) => void;
};
const uploads: Upload[] = [];

vi.mock("@/api/client", () => ({
  listAssets: vi.fn(async () => []),
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  importAsset: vi.fn(
    (params: { file: File; onProgress?: (fraction: number) => void; signal?: AbortSignal }) =>
      new Promise((resolve, reject) => {
        uploads.push({ file: params.file, onProgress: params.onProgress, signal: params.signal, resolve, reject });
        params.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")));
      }),
  ),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key, usePreferences: () => ({ locale: "zh" }) }));

import { AssetPickerDialog } from "./AssetPickerDialog";

beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {};
});
beforeEach(() => {
  uploads.length = 0;
});
afterEach(cleanup);

function mount(kind: "image" | "video" | "media" = "image") {
  const onPick = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AssetPickerDialog open kind={kind} workspaceId="ws" onOpenChange={vi.fn()} onPick={onPick} />
    </QueryClientProvider>,
  );
  return onPick;
}

const png = () => new File(["png"], "截图.png", { type: "image/png" });
const mp4 = () => new File(["mp4"], "开场.mp4", { type: "video/mp4" });
const fileInput = () => document.querySelector<HTMLInputElement>('input[type="file"]')!;
const dropOn = (target: Element, files: File[]) =>
  fireEvent.drop(target, { dataTransfer: { types: ["Files"], files, items: files.map((file) => ({ kind: "file", type: file.type })) } });

it("按钮选一个文件:传的时候看得见进度,传完就当是挑中了它", async () => {
  const onPick = mount("image");
  const button = screen.getByRole("button", { name: "boardsUploadLocal" });
  expect(fileInput().accept).toBe("image/*");
  const opened = vi.spyOn(fileInput(), "click");
  fireEvent.click(button);
  expect(opened).toHaveBeenCalled();
  fireEvent.change(fileInput(), { target: { files: [png()] } });
  await waitFor(() => expect(uploads).toHaveLength(1));
  expect(uploads[0].file.name).toBe("截图.png");
  act(() => uploads[0].onProgress?.(0.42));
  expect(screen.getByRole("status")).toHaveTextContent("assetUploading");
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("42");
  await act(async () => uploads[0].resolve({ id: "new", kind: "image", name: "截图" }));
  expect(onPick).toHaveBeenCalledWith({ id: "new", name: "截图", kind: "image" });
  expect(screen.queryByRole("status")).toBeNull();
});

it("拖进弹窗也传;种类不对就地说一句,不传", async () => {
  const onPick = mount("image");
  const dialog = screen.getByRole("dialog");
  dropOn(dialog, [mp4()]);
  expect(uploads).toHaveLength(0);
  expect(screen.getByRole("alert")).toHaveTextContent("assetUploadWrongKind");
  dropOn(dialog, [png()]);
  await waitFor(() => expect(uploads).toHaveLength(1));
  expect(screen.queryByRole("alert")).toBeNull();
  await act(async () => uploads[0].resolve({ id: "new", kind: "image", name: "截图" }));
  expect(onPick).toHaveBeenCalledTimes(1);
});

it("没传上说为什么,能再来一次;传的时候能停", async () => {
  mount("media");
  fireEvent.change(fileInput(), { target: { files: [mp4()] } });
  await waitFor(() => expect(uploads).toHaveLength(1));
  await act(async () => uploads[0].reject(new Error("磁盘满了")));
  expect(screen.getByRole("alert")).toHaveTextContent("assetUploadFailed");
  fireEvent.click(screen.getByRole("button", { name: /retry/ }));
  await waitFor(() => expect(uploads).toHaveLength(2));
  expect(uploads[1].file.name).toBe("开场.mp4");
  fireEvent.click(screen.getByRole("button", { name: "assetUploadCancel" }));
  expect(uploads[1].signal?.aborted).toBe(true);
  await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  expect(screen.queryByRole("alert")).toBeNull();
});
