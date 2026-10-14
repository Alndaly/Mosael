/** @vitest-environment jsdom */
/**
 * 大模型节点「要模型看的图片」的紧凑格子(AssetGridField)。
 *
 * 值是一串逗号分隔的素材 id,**顺序就是发给模型的顺序**。这里钉住:
 * - 格子按值的顺序渲染;× 移除写回新串;拖完(dnd-kit 的 dragEnd)新顺序写回。
 * - 点上传格开文件选择、拖文件到字段上走同一个上传入口(只收图片,一次一个)。
 * - 满 8 张:上传格、素材库格都不出现。
 * - 素材库格打开 AssetGridPicker:多选、角标标先后,确认把选择(按挑的顺序)写回。
 * - 进度不占格子:格子下面一行小字(在传第 i/n 个、失败给重试/取消)。
 *
 * 绑定那半(接上游 / `{{上游}}`)由外层 NodeConfigForm 裹,这里不测。
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

//: 上传走 useAssetUpload;这里钉住它的协议(一次一个、done 回素材),不真的发请求。
const uploadMock = vi.hoisted(() => ({
  state: { status: "idle" } as
    | { status: "idle" }
    | { status: "uploading"; name: string; progress: number }
    | { status: "failed"; name: string; reason: string }
    | { status: "rejected"; message: string },
  start: vi.fn(),
  reject: vi.fn(),
  retry: vi.fn(),
  cancel: vi.fn(),
  dismiss: vi.fn(),
}));

//: 抓到 DndContext 的 onDragEnd 直接调:jsdom 里没法真拖,排序写回逻辑照测。
const dndState = vi.hoisted(() => ({
  onDragEnd: undefined as undefined | ((event: { active: { id: string }; over: { id: string } | null }) => void),
}));

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/core")>();
  const React = await import("react");
  return {
    ...actual,
    DndContext: (props: React.ComponentProps<typeof actual.DndContext>) => {
      dndState.onDragEnd = props.onDragEnd as typeof dndState.onDragEnd;
      return React.createElement(React.Fragment, null, props.children);
    },
  };
});

vi.mock("@dnd-kit/sortable", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/sortable")>();
  const React = await import("react");
  return {
    ...actual,
    SortableContext: (props: { children: React.ReactNode }) => React.createElement(React.Fragment, null, props.children),
    //: 排序的写回逻辑在 dragEnd 里(arrayMove 是库里的纯函数);格子的拖柄外观/量位不测。
    useSortable: () => ({
      attributes: {},
      listeners: {},
      setNodeRef: () => {},
      transform: null,
      transition: undefined,
      isDragging: false,
    }),
  };
});

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

vi.mock("@/api/client", () => ({
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetFileUrl: (id: string) => `/file/${id}`,
}));

vi.mock("@/components/app/image-preview", () => ({
  useImagePreview: () => ({ openImagePreview: vi.fn(), isImagePreviewOpen: false }),
}));

vi.mock("@/features/boards/assetUpload", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/boards/assetUpload")>();
  return { ...actual, useAssetUpload: () => uploadMock };
});

/** 素材库里的三份图;`gone` 这个 id 不在库里(= 已被删)。 */
const LIBRARY = new Map<string, Record<string, unknown>>([
  ["img-a", { id: "img-a", kind: "image", name: "甲", original_filename: "a.png", source: "imported", derived: false, ai_generated: false, created_at: new Date().toISOString(), media_info: { width: 1024, height: 1024 } }],
  ["img-b", { id: "img-b", kind: "image", name: "乙", original_filename: "b.png", source: "imported", derived: false, ai_generated: false, created_at: new Date().toISOString(), media_info: { width: 800, height: 600 } }],
  ["img-c", { id: "img-c", kind: "image", name: "丙", original_filename: "c.png", source: "generated", derived: false, ai_generated: true, created_at: new Date().toISOString(), media_info: { width: 1920, height: 1080 } }],
]);

vi.mock("@/lib/assetQueries", () => ({
  useAssetDetails: (ids: readonly string[]) => ({
    byId: new Map(ids.flatMap((id) => (LIBRARY.has(id) ? [[id, LIBRARY.get(id)] as const] : []))),
    settled: true,
  }),
  useAssetSearch: () => ({
    text: "",
    search: vi.fn(),
    items: [...LIBRARY.values()],
    isLoading: false,
    isError: false,
    error: null,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    refetch: vi.fn(),
  }),
}));

import { AssetGridField } from "@/features/nodeForms/AssetGridField";

//: jsdom 里没有排版:网格量到的宽度给一个能放下几格的数,滚动区给一个高度(和 AssetGridPicker 自己的测试同一套)。
const clientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
const clientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get(this: HTMLElement) {
      return this.getAttribute("role") === "listbox" ? 720 : 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get(this: HTMLElement) {
      return this.hasAttribute("data-asset-grid-scroll") ? 600 : 0;
    },
  });
});
afterAll(() => {
  if (clientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", clientWidth);
  if (clientHeight) Object.defineProperty(HTMLElement.prototype, "clientHeight", clientHeight);
});

afterEach(() => {
  cleanup();
  dndState.onDragEnd = undefined;
});
beforeEach(() => {
  uploadMock.state = { status: "idle" };
  vi.clearAllMocks();
});

function renderField(value: unknown) {
  const onChange = vi.fn();
  const view = render(<AssetGridField value={value} workspaceId="w1" max={8} onChange={onChange} />);
  return { onChange, ...view };
}

const tileIds = (container: HTMLElement) =>
  [...container.querySelectorAll("[data-asset-tile]")].map((tile) => tile.getAttribute("data-asset-tile"));

/** 直接调捕获到的 onDragEnd(jsdom 里没法真拖):只带排序写回逻辑要的那两个 id。 */
const dragEnd = (event: { active: { id: string }; over: { id: string } | null }) =>
  dndState.onDragEnd?.(event);

describe("已挑的格子", () => {
  it("按值的顺序渲染,值是逗号分隔的素材 id 串", () => {
    const { container } = renderField("img-b,img-a,img-c");
    expect(tileIds(container)).toEqual(["img-b", "img-a", "img-c"]);
  });

  it("也收真列表(值可能来自上游插值)", () => {
    const { container } = renderField(["img-c", "img-a"]);
    expect(tileIds(container)).toEqual(["img-c", "img-a"]);
  });

  it("已删除的素材画占位、不当作图片", () => {
    const { container } = renderField("gone");
    const tile = container.querySelector("[data-asset-tile='gone']");
    expect(tile).not.toBeNull();
    expect(tile!.querySelector("img")).toBeNull();
    expect(tile!.getAttribute("aria-label")).toContain("wfAssetGridMissing");
  });

  it("× 移除:写回去掉那一张的新串", () => {
    const { container, onChange } = renderField("img-a,img-b,img-c");
    fireEvent.click(container.querySelector("[data-asset-tile='img-b'] button")!);
    expect(onChange).toHaveBeenCalledWith("img-a,img-c");
  });

  it("拖动排序:dragEnd 后新顺序写回(顺序就是发给模型的顺序)", () => {
    const { onChange } = renderField("img-a,img-b,img-c");
    expect(dndState.onDragEnd).toBeDefined();
    act(() => dragEnd({ active: { id: "img-a" }, over: { id: "img-c" } }));
    expect(onChange).toHaveBeenCalledWith("img-b,img-c,img-a");
  });

  it("拖到原处 / 松在格子外:不写回", () => {
    const { onChange } = renderField("img-a,img-b");
    act(() => dragEnd({ active: { id: "img-a" }, over: { id: "img-a" } }));
    act(() => dragEnd({ active: { id: "img-a" }, over: null }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("上传与上限", () => {
  it("点上传格打开文件选择(accept 只收图片)", () => {
    const { container } = renderField("");
    const chooser = container.querySelector<HTMLInputElement>("[data-asset-grid-chooser]")!;
    expect(chooser.accept).toBe("image/*");
    const click = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(container.querySelector("[data-upload-tile]")!);
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });

  it("选定文件走上传(一次一个),传完把素材 id 追加进值", () => {
    const { container, onChange } = renderField("img-a");
    const file = new File(["x"], "new.png", { type: "image/png" });
    fireEvent.change(container.querySelector("[data-asset-grid-chooser]")!, { target: { files: [file] } });
    expect(uploadMock.start).toHaveBeenCalledTimes(1);
    const done = uploadMock.start.mock.calls[0][1] as (asset: { id: string }) => void;
    done({ id: "fresh-1" });
    expect(onChange).toHaveBeenCalledWith("img-a,fresh-1");
  });

  it("把文件拖到字段上 = 上传;不是图片不收、就地说原因", () => {
    const { container } = renderField("");
    const field = container.querySelector("[data-asset-grid]")!;
    const image = new File(["x"], "drop.png", { type: "image/png" });
    fireEvent.drop(field, { dataTransfer: { files: [image], types: ["Files"] } });
    expect(uploadMock.start).toHaveBeenCalledWith(image, expect.any(Function));
    const video = new File(["x"], "clip.mp4", { type: "video/mp4" });
    fireEvent.drop(field, { dataTransfer: { files: [video], types: ["Files"] } });
    expect(uploadMock.reject).toHaveBeenCalled();
    expect(uploadMock.start).toHaveBeenCalledTimes(1);
  });

  it("满 8 张:上传格、素材库格都不出现", () => {
    const { container } = renderField(Array.from({ length: 8 }, (_, at) => `full-${at}`).join(","));
    expect(container.querySelectorAll("[data-asset-tile]")).toHaveLength(8);
    expect(container.querySelector("[data-upload-tile]")).toBeNull();
    expect(container.querySelector("[data-add-tile]")).toBeNull();
  });

  it("没满:末尾是上传格 + 素材库格(虚线,缺图不占这两格的位置)", () => {
    const { container } = renderField("img-a");
    expect(container.querySelector("[data-upload-tile]")).not.toBeNull();
    expect(container.querySelector("[data-add-tile]")).not.toBeNull();
  });

  it("上传中/失败:格子下面一行小字,不占格子;失败给重试和取消", () => {
    const { onChange, rerender } = renderField("img-a");
    uploadMock.state = { status: "uploading", name: "u.png", progress: 0.5 };
    rerender(<AssetGridField value="img-a" workspaceId="w1" max={8} onChange={onChange} />);
    const row = screen.getByRole("status");
    expect(row).toHaveAttribute("data-asset-grid-upload", "uploading");
    expect(row.className).toContain("text-ui-2xs");
    uploadMock.state = { status: "failed", name: "u.png", reason: "boom" };
    rerender(<AssetGridField value="img-a" workspaceId="w1" max={8} onChange={onChange} />);
    expect(screen.getByRole("alert")).toHaveAttribute("data-asset-grid-upload", "failed");
    fireEvent.click(screen.getByText("retry"));
    expect(uploadMock.retry).toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("close"));
    expect(uploadMock.dismiss).toHaveBeenCalled();
  });
});

describe("素材库挑图", () => {
  it("点素材库格打开挑图弹窗;多选确认后按挑的顺序写回", () => {
    const { container, onChange } = renderField("");
    fireEvent.click(container.querySelector("[data-add-tile]")!);
    //: 弹窗开着(标题在),库里三份图列成格子。
    expect(screen.getByText("wfAssetGridPickTitle")).toBeInTheDocument();
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(3);
    fireEvent.click(options[1]);
    fireEvent.click(options[0]);
    //: 角标标先后:先点的那个标 1(角标格子自己是那个带 bg-action 的圆标;它外层的
    //: 缩略图壳 span 包着它,textContent 也是同一个数字,所以不能按「纯数字 span」查)。
    const badges = [...document.querySelectorAll("[data-asset-grid-scroll] span.bg-action")]
      .map((span) => span.textContent?.trim() ?? "");
    expect(badges.sort()).toEqual(["1", "2"]);
    fireEvent.click(document.querySelector("[data-asset-grid-confirm]")!);
    expect(onChange).toHaveBeenCalledWith("img-b,img-a");
  });

  it("确认把整份选择写回:弹窗里去掉已挑的 = 写回里没有它", () => {
    const { container, onChange } = renderField("img-a,img-b");
    fireEvent.click(container.querySelector("[data-add-tile]")!);
    //: 打开时已挑好 img-a、img-b;点 img-a 那一格 = 取消挑它。
    fireEvent.click(screen.getAllByRole("option")[0]);
    fireEvent.click(document.querySelector("[data-asset-grid-confirm]")!);
    expect(onChange).toHaveBeenCalledWith("img-b");
  });
});
