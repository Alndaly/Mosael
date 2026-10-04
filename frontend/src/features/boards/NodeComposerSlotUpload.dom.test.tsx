/** @vitest-environment jsdom */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";

/**
 * 生成面板上方的「+」槽**直接收本地文件**:把文件拖到「+」上、或者在面板里 ⌘V 粘一张截图 —— 传进素材库就挂进槽里,
 * 不必先打开弹窗。只收这个槽要的那一种(图片槽拖进一段视频就地说一句);传的时候能停,没传上说为什么。
 */

type Upload = { file: File; signal?: AbortSignal; resolve: (asset: unknown) => void; reject: (error: unknown) => void };
const uploads: Upload[] = [];

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  importAsset: vi.fn(
    (params: { file: File; signal?: AbortSignal }) =>
      new Promise((resolve, reject) => {
        uploads.push({ file: params.file, signal: params.signal, resolve, reject });
        params.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")));
      }),
  ),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }), useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));
vi.mock("./PromptEditor", () => ({ PromptEditor: () => <textarea aria-label="prompt" />, restorePromptDocument: vi.fn(), textDocument: vi.fn(), collect: () => [] }));

import { ImagePreviewProvider } from "@/components/app/image-preview";
import { NodeComposer } from "./NodeComposer";

beforeEach(() => {
  uploads.length = 0;
});

function model(capabilities: Record<string, unknown>, kind: "image" | "video" = "image"): GenerationOption {
  return {
    id: "m", provider_profile_id: "p", plugin_instance_id: "", profile_name: "T", label: "L", adapter_available: true, is_default: true,
    capabilities_known: true, provider: "test", model: "m", kind, capabilities: { prompt: "optional", ...capabilities },
  } as GenerationOption;
}

function mount(option: GenerationOption, kind: "image" | "video" = "image") {
  const onFormChange = vi.fn();
  render(
    <ImagePreviewProvider>
      <NodeComposer
        item={{ id: "cell", kind, text: "" } as BoardItem}
        models={[option]}
        busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={onFormChange} onSubmit={vi.fn()}
      />
    </ImagePreviewProvider>,
  );
  return onFormChange;
}

const png = () => new File(["png"], "截图.png", { type: "image/png" });
const mp4 = () => new File(["mp4"], "开场.mp4", { type: "video/mp4" });
const dropOn = (target: Element, files: File[]) =>
  fireEvent.drop(target, { dataTransfer: { types: ["Files"], files, items: files.map((file) => ({ kind: "file", type: file.type })) } });
const attached = (onFormChange: ReturnType<typeof vi.fn>) =>
  (onFormChange.mock.lastCall?.[0] as { source_assets?: unknown[] } | undefined)?.source_assets;

//: 参考图、参考视频各一种媒体:面板上收成**一个**「+」,拖上来的文件按它自己的种类挂进对应的槽。
const REFERENCES = {
  parameter_keys: ["reference_image", "reference_video"], source_limits: { reference_image: 2, reference_video: 1 },
};

it("把图片拖到「+」上:传进素材库,挂进参考图槽", async () => {
  const onFormChange = mount(model(REFERENCES));
  dropOn(screen.getByRole("button", { name: "boardAddSource" }), [png()]);
  await waitFor(() => expect(uploads).toHaveLength(1));
  expect(screen.getByRole("status")).toHaveTextContent("assetUploading");
  await act(async () => uploads[0].resolve({ id: "new", kind: "image", name: "截图" }));
  await waitFor(() => expect(attached(onFormChange)).toEqual([{ asset_id: "new", role: "reference_image" }]));
  expect(screen.queryByRole("status")).toBeNull();
});

it("面板里 ⌘V 一张截图:同样传上去挂进槽;剪贴板里没有文件就不管(照常粘字)", async () => {
  const onFormChange = mount(model(REFERENCES));
  const panel = document.querySelector("[data-board-composer]")!;
  fireEvent.paste(screen.getByRole("textbox", { name: "prompt" }), { clipboardData: { files: [], types: ["text/plain"] } });
  expect(uploads).toHaveLength(0);
  fireEvent.paste(panel, { clipboardData: { files: [new File(["png"], "", { type: "image/png" })], types: ["Files"] } });
  await waitFor(() => expect(uploads).toHaveLength(1));
  expect(uploads[0].file.name).toMatch(/^pasted-.*\.png$/);
  await act(async () => uploads[0].resolve({ id: "shot", kind: "image", name: "pasted" }));
  await waitFor(() => expect(attached(onFormChange)).toEqual([{ asset_id: "shot", role: "reference_image" }]));
});

it("首帧槽只收图片:拖进一段视频就地说一句;没传上说为什么,能停", async () => {
  const frames = model({ parameter_keys: ["first_frame", "last_frame"], source_limits: { first_frame: 1, last_frame: 1 } }, "video");
  const onFormChange = mount(frames, "video");
  const first = screen.getByRole("button", { name: "genFirstFrame" });
  expect(first).toBeDefined();
  dropOn(first, [mp4()]);
  expect(uploads).toHaveLength(0);
  expect(screen.getByRole("alert")).toHaveTextContent("assetUploadWrongKind");
  dropOn(first, [png()]);
  await waitFor(() => expect(uploads).toHaveLength(1));
  await act(async () => uploads[0].reject(new Error("断网了")));
  expect(screen.getByRole("alert")).toHaveTextContent("assetUploadFailed");
  fireEvent.click(screen.getByRole("button", { name: /retry/ }));
  await waitFor(() => expect(uploads).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "assetUploadCancel" }));
  expect(uploads[1].signal?.aborted).toBe(true);
  expect(attached(onFormChange) ?? []).toEqual([]);
});
