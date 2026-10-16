/** @vitest-environment jsdom */
/**
 * 「一次挑一组素材」的那一个共用格子(AssetGridField)。
 *
 * **两种值编码由声明决定**,这里两种都钉住:
 * - 逗号分隔的素材 id 串(大模型节点那一格,**顺序就是发给模型的顺序**);
 * - 一行一条 `素材id:角色`(声明了 `lines` + `entry_labels: "source_roles"`:生成节点的「输入素材」)
 *   —— 写回去的必须是**行的列表**,角色挂在每一份上。
 *
 * 还钉住:格子按值的顺序渲染;× 移除;拖完(dnd-kit 的 dragEnd)新顺序写回;上传(收哪几类由 `media`
 * 说);满上限两格虚线格消失;素材库格开 AssetGridPicker(按 `media` 筛)多选、角标标先后、确认写回;
 * 角色角标点开换角色;自动来的那几处引用单独一行(× 进排除清单、模型不收就说、不是那类素材就标)。
 *
 * 绑定那半(接上游 / `{{上游}}`、`{{…}}` 那一行)由外层 NodeConfigForm 裹,这里不测。
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
  //: 插值那两句按**真模板**给:只回 key 的话 `.replace("{kind}", …)` 什么也换不着,
  //: 而这两条要看的正是「说的是哪一类素材 / 哪个角色」。
  useI18n: () => (key: string) =>
    key === "wfGenAutoSourcesWrongKind" ? "不是{kind},不会发送"
    : key === "wfGenAutoSourcesRejected" ? "这个模型不接受{role},不会被送进去"
    : key,
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

//: 上传走 useAssetUpload;这里钉住它的协议(一次一个、done 回素材),不真的发请求。
//: 它的家是中立的 components/generation/assetUpload(见 features/featureBoundaries.test.ts),不从 boards 绕。
vi.mock("@/components/generation/assetUpload", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/generation/assetUpload")>();
  return { ...actual, useAssetUpload: () => uploadMock };
});

/** 素材库里的三份图;`gone` 这个 id 不在库里(= 已被删)。 */
const LIBRARY = new Map<string, Record<string, unknown>>([
  ["img-a", { id: "img-a", kind: "image", name: "甲", original_filename: "a.png", source: "imported", derived: false, ai_generated: false, created_at: new Date().toISOString(), media_info: { width: 1024, height: 1024 } }],
  ["img-b", { id: "img-b", kind: "image", name: "乙", original_filename: "b.png", source: "imported", derived: false, ai_generated: false, created_at: new Date().toISOString(), media_info: { width: 800, height: 600 } }],
  ["img-c", { id: "img-c", kind: "image", name: "丙", original_filename: "c.png", source: "generated", derived: false, ai_generated: true, created_at: new Date().toISOString(), media_info: { width: 1920, height: 1080 } }],
  ["clip-v", { id: "clip-v", kind: "video", name: "一段视频", original_filename: "v.mp4", source: "imported", derived: false, ai_generated: false, created_at: new Date().toISOString(), media_info: { width: 1920, height: 1080 } }],
]);

vi.mock("@/lib/assetQueries", () => ({
  useAssetDetails: (ids: readonly string[]) => ({
    byId: new Map(ids.flatMap((id) => (LIBRARY.has(id) ? [[id, LIBRARY.get(id)] as const] : []))),
    settled: true,
  }),
  //: 和真那一份一样按 `kind` 筛:挑图弹窗只列图片(库里那份视频不该出现在候选项里)。
  useAssetSearch: (query?: { kind?: readonly string[] }) => ({
    text: "",
    search: vi.fn(),
    items: [...LIBRARY.values()].filter((one) => !query?.kind || query.kind.includes(String(one.kind))),
    isLoading: false,
    isError: false,
    error: null,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    refetch: vi.fn(),
  }),
}));

import { AssetGridField, assetGridMax, assetGridRoles } from "@/features/nodeForms/AssetGridField";
import { SOURCE_ROLES } from "@/lib/sourceFrames";

//: 这些纯函数只做「声明 → 控件参数」的翻译,文案原样还回来就够断言了。
const keyText = (key: string) => key as never;

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

/** 大模型节点那一格的声明:只收图片、值是一串逗号分隔的素材 id、上限 8。 */
function renderField(value: unknown, media: readonly string[] | null = ["image"]) {
  const onChange = vi.fn();
  const view = render(
    <AssetGridField value={value} workspaceId="w1" media={media} max={8} onChange={onChange} />,
  );
  return { onChange, ...view };
}

/** 生成节点「输入素材」那一格的声明:一行一条 `素材id:角色`,角色来自模型描述符。 */
const ROLES = [
  { value: "first_frame", label: "首帧", accepted: true, limit: 1 },
  { value: "reference_image", label: "参考图", accepted: true, limit: 2 },
  { value: "reference_video", label: "参考视频", accepted: false, limit: 1 },
];

function renderLines({
  value,
  roles = ROLES,
  defaultRole = "reference_image",
  refs = [],
  excluded = [],
  roleOverrides = {},
  variables = [],
  max = 3,
}: {
  value: unknown;
  roles?: Array<{ value: string; label: string; accepted?: boolean; limit?: number; slots?: readonly string[] }> | null;
  defaultRole?: string;
  refs?: Array<{ path: string; label: string; assetId: string | null }>;
  excluded?: string[];
  roleOverrides?: Record<string, string>;
  variables?: string[];
  max?: number;
}) {
  const onChange = vi.fn();
  const onExcludedChange = vi.fn();
  const onRoleOverrideChange = vi.fn();
  const view = render(
    <AssetGridField
      value={value}
      workspaceId="w1"
      lines
      roles={roles}
      defaultRole={defaultRole}
      max={max}
      refs={refs}
      excluded={excluded}
      roleOverrides={roleOverrides}
      onRoleOverrideChange={onRoleOverrideChange}
      onExcludedChange={onExcludedChange}
      variables={variables}
      onChange={onChange}
    />,
  );
  return { onChange, onExcludedChange, onRoleOverrideChange, ...view };
}

/** 带**自动来的引用**那一块渲染(见 workflows/referencedImages:提示词里引用到的图)。 */
function renderAuto({
  value = "",
  refs,
  excluded = [],
  max = 8,
}: {
  value?: unknown;
  refs: Array<{ path: string; label: string; assetId: string | null }>;
  excluded?: string[];
  max?: number;
}) {
  const onChange = vi.fn();
  const onExcludedChange = vi.fn();
  const view = render(
    <AssetGridField
      value={value}
      workspaceId="w1"
      media={["image"]}
      max={max}
      refs={refs}
      excluded={excluded}
      onExcludedChange={onExcludedChange}
      onChange={onChange}
    />,
  );
  return { onChange, onExcludedChange, ...view };
}

const REF = { path: "pic.asset_id", label: "画图 · 素材", assetId: "img-a" };

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

  it("把文件拖到字段上 = 上传;media 不声明的那几类不收、就地说原因", () => {
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

  it("media 声明了 image + video:视频也收(实体保存那一格挂参考图就是两种都要)", () => {
    const { container } = renderField("", ["image", "video"]);
    expect(container.querySelector<HTMLInputElement>("[data-asset-grid-chooser]")!.accept).toBe("image/*,video/*");
    const video = new File(["x"], "clip.mp4", { type: "video/mp4" });
    fireEvent.drop(container.querySelector("[data-asset-grid]")!, { dataTransfer: { files: [video], types: ["Files"] } });
    expect(uploadMock.start).toHaveBeenCalledWith(video, expect.any(Function));
    expect(uploadMock.reject).not.toHaveBeenCalled();
  });

  it("没声明 media 的格子:图片 / 视频 / 音频都收", () => {
    const { container } = renderField("", null);
    expect(container.querySelector<HTMLInputElement>("[data-asset-grid-chooser]")!.accept).toBe("image/*,video/*,audio/*");
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

describe("自动来的引用(「引用即发送」)", () => {
  const chip = (container: HTMLElement, path: string) => container.querySelector(`[data-auto-image-ref="${path}"]`);

  it("没有引用时那一块不出现(不占地方)", () => {
    const { container } = renderField("img-a");
    expect(container.querySelector("[data-auto-images]")).toBeNull();
  });

  it("有引用时和手动挑的分开摆:名字是引用(「画图 · 素材」)、来源写在数据属性上,还说得清为什么", () => {
    const { container } = renderAuto({ refs: [REF] });
    const block = container.querySelector("[data-auto-images]")!;
    expect(block).not.toBeNull();
    //: 自动来的那几处不在手动格子那一片里(缩略图那一侧一个都没多)。
    expect(tileIds(container)).toEqual([]);
    const one = chip(container, "pic.asset_id")!;
    expect(one.textContent).toContain("画图 · 素材");
    expect(one.getAttribute("data-auto-image-on")).toBe("true");
    //: 一行说明 + 这一处引用自己:来源看得见。
    expect(block.textContent).toContain("wfAssetGridAutoTitle");
    expect(block.textContent).toContain("wfAssetGridAutoHint");
  });

  it("× 去掉一处:把引用路径写进排除清单(运行时的取图认它)", () => {
    const { container, onExcludedChange } = renderAuto({ refs: [REF], excluded: ["other.ref"] });
    fireEvent.click(chip(container, "pic.asset_id")!.querySelector("[data-auto-image-toggle]")!);
    expect(onExcludedChange).toHaveBeenCalledWith(["other.ref", "pic.asset_id"]);
  });

  it("已排除的那一处还在(看得见、点得回来):状态是关,再点从清单里去掉", () => {
    const { container, onExcludedChange } = renderAuto({ refs: [REF], excluded: ["pic.asset_id"] });
    const one = chip(container, "pic.asset_id")!;
    expect(one.getAttribute("data-auto-image-on")).toBe("false");
    fireEvent.click(one.querySelector("[data-auto-image-toggle]")!);
    expect(onExcludedChange).toHaveBeenCalledWith([]);
  });

  it("静态就知道不是图片的(引用了视频素材):就地说它不会发送", () => {
    const { container } = renderAuto({ refs: [{ path: "clip.asset_id", label: "一段片 · 素材", assetId: "clip-v" }] });
    const one = chip(container, "clip.asset_id")!;
    const skipped = one.querySelector("[data-auto-image-skipped]")!;
    expect(skipped).not.toBeNull();
    expect(skipped.textContent).toContain("kindVideo");
  });

  it("手动挑的加引用来的超过上限:当场说清,而不是等运行时报「最多 8 张」", () => {
    const refs = Array.from({ length: 3 }, (_, at) => ({ path: `n${at}.asset_id`, label: `第 ${at} 张`, assetId: null }));
    const { container } = renderAuto({ value: "img-a,img-b,img-c,img-d,img-e,img-f", refs });
    expect(container.querySelector("[data-auto-images-over]")).not.toBeNull();
  });

  it("没超上限就没有那一句", () => {
    const { container } = renderAuto({ refs: [REF] });
    expect(container.querySelector("[data-auto-images-over]")).toBeNull();
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

describe("一行一条 `素材id:角色`(生成节点的「输入素材」)", () => {
  const tileRoles = (container: HTMLElement) =>
    [...container.querySelectorAll("[data-asset-tile]")].map((tile) => tile.getAttribute("data-asset-tile-role"));

  it("值是行的列表,每一份挂着自己的角色;写回的也是**行的列表**(不是逗号串)", () => {
    const { container, onChange } = renderLines({ value: ["img-a:first_frame", "img-b:reference_image"] });
    expect(container.querySelector("[data-asset-grid]")!.getAttribute("data-asset-grid-mode")).toBe("lines");
    expect(tileIds(container)).toEqual(["img-a", "img-b"]);
    expect(tileRoles(container)).toEqual(["first_frame", "reference_image"]);
    fireEvent.click(container.querySelector("[data-asset-tile='img-a'] button[aria-label]")!);
    //: × 移除第一份:写回的是列表,角色原样跟在值后面。
    expect(onChange).toHaveBeenCalledWith(["img-b:reference_image"]);
  });

  it("没写角色的那一行**原样留着**(后端按种类给默认,这里不替它猜)", () => {
    const { container, onChange } = renderLines({ value: ["img-a", "img-b:first_frame"] });
    expect(tileRoles(container)).toEqual([null, "first_frame"]);
    //: 换第一份的角色:值变成 `id:角色`,第二行一个字节都不动。
    fireEvent.click(container.querySelector("[data-role-badge='']")!);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "首帧" }));
    expect(onChange).toHaveBeenCalledWith(["img-a:first_frame", "img-b:first_frame"]);
  });

  it("角色角标:点开是声明里那几种角色,选一个就把这一份的角色换掉", () => {
    const { container, onChange } = renderLines({ value: ["img-a:reference_image"] });
    expect(container.querySelector("[data-role-badge='reference_image']")!.textContent).toContain("参考图");
    fireEvent.click(container.querySelector("[data-role-badge='reference_image']")!);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "首帧" }));
    expect(onChange).toHaveBeenCalledWith(["img-a:first_frame"]);
  });

  it("模型收不下的角色在菜单里标出来,但**照样列着**(换一个收得下的就能发)", () => {
    const { container } = renderLines({ value: ["img-a:reference_image"] });
    fireEvent.click(container.querySelector("[data-role-badge='reference_image']")!);
    const items = screen.getAllByRole("menuitemradio");
    expect(items.map((one) => one.textContent)).toEqual(["首帧", "参考图", "参考视频wfAssetGridRoleUnsupported"]);
  });

  it("**没有**角色声明的格子不长角标(三个 asset_ids 那一类)", () => {
    const { container } = renderLines({ value: ["img-a"], roles: null });
    expect(container.querySelector("[data-role-badge]")).toBeNull();
  });

  it("自动来的那一份也有角色角标:默认是声明里的那个,改一下记在 `<字段>_roles`", () => {
    const { container, onRoleOverrideChange } = renderLines({
      value: [],
      refs: [REF],
    });
    const chip = container.querySelector("[data-auto-image-ref='pic.asset_id']")!;
    expect(chip.getAttribute("data-auto-image-role")).toBe("reference_image");
    fireEvent.click(chip.querySelector("[data-role-badge='reference_image']")!);
    fireEvent.click(screen.getByRole("menuitemradio", { name: "首帧" }));
    expect(onRoleOverrideChange).toHaveBeenCalledWith("pic.asset_id", "first_frame");
  });

  it("自动来的那一份按改过的角色发(`roleOverrides`)", () => {
    const { container } = renderLines({ value: [], refs: [REF], roleOverrides: { "pic.asset_id": "first_frame" } });
    expect(
      container.querySelector("[data-auto-image-ref='pic.asset_id']")!.getAttribute("data-auto-image-role"),
    ).toBe("first_frame");
  });

  it("模型不收这个角色:明说不会被送进去", () => {
    const { container } = renderLines({
      value: [],
      refs: [REF],
      roles: [{ value: "first_frame", label: "首帧", accepted: true, limit: 1 }, { value: "reference_image", label: "参考图", accepted: false, limit: 1 }],
    });
    const rejected = container.querySelector("[data-auto-image-rejected]")!;
    expect(rejected).not.toBeNull();
    expect(rejected.textContent).toBe("这个模型不接受参考图,不会被送进去");
  });

  it("每个角色能挂几份 / 槽位叫什么:写在格子下面(描述符的 source_limits / source_labels)", () => {
    const { container } = renderLines({
      value: [],
      roles: [{ value: "reference_image", label: "参考图", accepted: true, limit: 9, slots: ["人物", "背景"] }],
    });
    const notes = container.querySelector("[data-asset-grid-role-notes]")!;
    expect(notes).not.toBeNull();
    expect(notes.textContent).toContain("wfGenSourceMultiHint");
    expect(notes.textContent).toContain("wfGenSourceSlotNames");
  });

  it("能接上游输出:一行「再加一份」的输入,挑完接在末尾并带上默认角色", async () => {
    const { container, onChange } = renderLines({
      value: ["img-a:first_frame"],
      variables: ["{{up.asset_id}}"],
    });
    const row = container.querySelector("[data-asset-grid-ref]")!;
    expect(row).not.toBeNull();
    const trigger = row.querySelector('[role="combobox"]')!;
    //: 这是一个组合框(挑上游输出用的是它):点开而不是像下拉那样按回车。
    fireEvent.click(trigger);
    const options = await screen.findAllByRole("option");
    expect(options.map((one) => one.textContent).join(" ")).toContain("asset_id");
    fireEvent.click(options[0]);
    expect(onChange).toHaveBeenCalledWith(["img-a:first_frame", "{{up.asset_id}}:reference_image"]);
  });
});

describe("声明 → 控件参数(纯函数)", () => {
  it("`entry_labels` 不是 `source_roles` 就没有角色词表(那三个 asset_ids 不长得角标)", () => {
    expect(assetGridRoles(undefined, undefined, keyText)).toBeNull();
    expect(assetGridRoles("generation_parameters", undefined, keyText)).toBeNull();
  });

  it("词表就是 lib/sourceFrames 那一份;收不收由**模型事实**说,认不出模型就不下结论", () => {
    const roles = assetGridRoles(
      "source_roles",
      { accepted: ["reference_image"], limits: { reference_image: 9 }, slots: { reference_image: ["人物"] } },
      keyText,
    )!;
    expect(roles.map((one) => one.value)).toEqual([...SOURCE_ROLES]);
    expect(roles.find((one) => one.value === "reference_image")).toMatchObject({
      label: "genReferenceImage", accepted: true, limit: 9, slots: ["人物"],
    });
    expect(roles.find((one) => one.value === "first_frame")!.accepted).toBe(false);
    //: 还没认出模型(`accepted: null`):一个都不标。
    const unknown = assetGridRoles("source_roles", { accepted: null }, keyText)!;
    expect(unknown.every((one) => one.accepted === undefined)).toBe(true);
  });

  it("上限:带角色的格子按每个角色能挂几份**加起来**,没角色的格子还是 8", () => {
    expect(assetGridMax(null)).toBe(8);
    expect(assetGridMax(assetGridRoles("source_roles", { accepted: ["reference_image"], limits: { reference_image: 9 } }, keyText))).toBe(9);
    expect(assetGridMax(assetGridRoles("source_roles", { accepted: ["first_frame", "last_frame"] }, keyText))).toBe(2);
  });
});
