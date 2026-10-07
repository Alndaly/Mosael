/** @vitest-environment jsdom */
import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

/**
 * 挑媒体的网格(画板挑素材、挂参考图、替换媒体共用)。维护者嫌原来那个「一行一个、36px 小图」的清单丑,而且同名的
 * 四份「Generation · girl.json」长得一模一样、分不出来。这里钉住:一格一份,格子下面写得出它是什么、多大、哪来的、
 * 多久以前;键盘能在格子之间走、回车挑;先选再确认的几种(多选、替换)选中的格子说得出来;用过的点不动。
 */

const openImagePreview = vi.hoisted(() => vi.fn());
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview, isImagePreviewOpen: false }) }));
vi.mock("@/api/client", () => ({
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetFileUrl: (id: string) => `/file/${id}`,
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "viewFullSizeOf" ? "看大图:{name}" : key),
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AssetGridPicker, type GridAsset } from "./AssetGridPicker";

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const zhAgo = (minutes: number) => new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" }).format(-minutes, "minute");

function asset(id: string, over: Partial<GridAsset> = {}): GridAsset {
  return {
    id,
    kind: "image",
    name: id,
    original_filename: `${id}.png`,
    source: "imported",
    derived: false,
    ai_generated: false,
    created_at: ago(60 * 24 * 3),
    media_info: { width: 1024, height: 1536 },
    ...over,
  };
}

//: jsdom 里没有排版:网格量到的宽度给一个能放下四格的数(和真弹窗里一样一行几格地走),滚动区给一个高度。
const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
const height = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
beforeAll(() => {
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
  if (width) Object.defineProperty(HTMLElement.prototype, "clientWidth", width);
  if (height) Object.defineProperty(HTMLElement.prototype, "clientHeight", height);
});
afterEach(() => {
  cleanup();
  openImagePreview.mockReset();
});

function mount(props: Partial<React.ComponentProps<typeof AssetGridPicker<GridAsset>>> = {}) {
  const onActivate = vi.fn();
  const view = render(
    <AssetGridPicker
      open
      onOpenChange={() => {}}
      title="从素材库挑一份"
      searchLabel="按名字找"
      query=""
      onQueryChange={() => {}}
      items={[]}
      onActivate={onActivate}
      empty={{ icon: null, title: "素材库里还没有图片" }}
      {...props}
    />,
  );
  return { onActivate, ...view };
}

const tiles = () => screen.getAllByRole("option");
const describedText = (tile: HTMLElement) => document.getElementById(tile.getAttribute("aria-describedby") ?? "")?.textContent ?? "";

describe("一格一份", () => {
  it("同名的几份分得开:格子下面写着种类、尺寸、来源和多久以前", () => {
    mount({
      mixedKinds: true,
      items: [
        asset("a", { name: "Generation · girl.json", source: "generated", ai_generated: true, created_at: ago(3) }),
        asset("b", { name: "Generation · girl.json", created_at: ago(17) }),
        asset("v", { kind: "video", name: "开场", media_info: { width: 1280, height: 720, duration: 12 } }),
        asset("s", { kind: "audio", name: "旁白", media_info: { duration: 42 } }),
      ],
    });
    const [first, second, video, audio] = tiles();
    //: 读屏念的名字只是名字;是什么、多大、哪来的是它的说明。
    expect(first).toHaveAccessibleName("Generation · girl.json");
    expect(describedText(first)).toBe(`kindImage · 1024×1536mediaSourceGenerated · ${zhAgo(3)}`);
    expect(describedText(second)).toBe(`kindImage · 1024×1536mediaSourceImported · ${zhAgo(17)}`);
    //: 视频右下角是时长;音频没有尺寸,写时长,画一条波形而不是一张碎图。
    expect(video.textContent).toContain("00:12.0");
    expect(describedText(audio)).toContain("kindAudio · 00:42.0");
    expect(audio.querySelector("img")).toBeNull();
    expect(audio.querySelector("svg")).not.toBeNull();
  });

  it("只列一种时不写种类;图和视频有「看大图」,点它不算挑", () => {
    const { onActivate } = mount({ items: [asset("a"), asset("s", { kind: "audio", media_info: { duration: 5 } })] });
    expect(describedText(tiles()[0]).startsWith("1024×1536")).toBe(true);
    expect(screen.queryByRole("button", { name: "看大图:s" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "看大图:a" }));
    expect(openImagePreview).toHaveBeenCalledWith({ src: "/preview/a", title: "a", gallery: [{ src: "/preview/a", title: "a" }] });
    expect(onActivate).not.toHaveBeenCalled();
    fireEvent.click(tiles()[1]);
    expect(onActivate).toHaveBeenCalledWith(expect.objectContaining({ id: "s" }));
  });
});

describe("键盘", () => {
  const six = ["a", "b", "c", "d", "e", "f"].map((id) => asset(id));

  it("搜索框里回车挑高亮的那一格;悬停换高亮", () => {
    const { onActivate } = mount({ items: six });
    const search = screen.getByRole("textbox", { name: "按名字找" });
    expect(tiles()[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.mouseMove(tiles()[2]);
    expect(tiles()[2]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(search, { key: "Enter" });
    expect(onActivate).toHaveBeenCalledWith(six[2]);
  });

  it("↓ 进网格,方向键按行列走(一行四格),回车挑;第一行再 ↑ 回到搜索框", async () => {
    const user = userEvent.setup();
    const { onActivate } = mount({ items: six });
    const search = screen.getByRole("textbox", { name: "按名字找" });
    search.focus();
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(tiles()[0]);
    await user.keyboard("{ArrowRight}{ArrowDown}");
    //: 第二行只有两格:从第二格往下落在它正下方(第六格)。
    expect(document.activeElement).toBe(tiles()[5]);
    await user.keyboard("{ArrowUp}{ArrowLeft}");
    expect(document.activeElement).toBe(tiles()[0]);
    //: 只有一格能 Tab 到(高亮的那一格),其余的方向键走。
    expect(tiles().filter((one) => one.tabIndex === 0)).toEqual([tiles()[0]]);
    await user.keyboard("{End}{Enter}");
    expect(onActivate).toHaveBeenLastCalledWith(six[5]);
    await user.keyboard("{Home}{ArrowUp}");
    expect(document.activeElement).toBe(search);
  });
});

describe("先选再确认、用过的", () => {
  it("多选:选中的格子说得出来,角上是挑的先后", () => {
    const picked = ["c", "a"];
    mount({
      items: [asset("a"), asset("b"), asset("c")],
      selection: { isSelected: (one) => picked.includes(one.id), order: (one) => picked.indexOf(one.id), multiple: true },
    });
    expect(screen.getByRole("listbox")).toHaveAttribute("aria-multiselectable", "true");
    expect(tiles().map((one) => one.getAttribute("aria-selected"))).toEqual(["true", "false", "true"]);
    expect(within(tiles()[0]).getByText("2")).toBeInTheDocument();
    expect(within(tiles()[2]).getByText("1")).toBeInTheDocument();
  });

  it("用过的照样列着、写着为什么,点不动,回车也挑不到它", () => {
    const { onActivate } = mount({ items: [asset("a"), asset("b")], taken: (one) => (one.id === "a" ? "已挂上" : null) });
    const [used, free] = tiles();
    expect(used).toHaveAttribute("aria-disabled", "true");
    expect(within(used).getByText("已挂上")).toBeInTheDocument();
    fireEvent.click(used);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "按名字找" }), { key: "Enter" });
    expect(onActivate).not.toHaveBeenCalled();
    expect(free).not.toHaveAttribute("aria-disabled");
  });
});

describe("只画看得见的几行", () => {
  it("弹窗打开之后往下滚,后面的行跟着画出来", async () => {
    //: 滚动区在弹窗的 Portal 里、比组件晚挂上:曾经只在打开之前看过一眼滚动区(那时还没有),滚到底下一片空白。
    const many = Array.from({ length: 80 }, (_, index) => asset(`a${index}`));
    const props = {
      onOpenChange: () => {},
      title: "从素材库挑一份",
      searchLabel: "按名字找",
      query: "",
      onQueryChange: () => {},
      items: many,
      onActivate: () => {},
      empty: { icon: null, title: "" },
    };
    const { rerender } = render(<AssetGridPicker open={false} {...props} />);
    rerender(<AssetGridPicker open {...props} />);
    expect(screen.queryByRole("option", { name: "a79" })).toBeNull();
    const scroller = document.querySelector<HTMLElement>("[data-asset-grid-scroll]")!;
    //: 真浏览器里网格的顶边随滚动往上走;jsdom 不排版,照着 scrollTop 给。
    const grid = screen.getByRole("listbox");
    vi.spyOn(grid, "getBoundingClientRect").mockImplementation(() => ({ top: -scroller.scrollTop }) as DOMRect);
    scroller.scrollTop = 3600;
    fireEvent.scroll(scroller);
    expect(await screen.findByRole("option", { name: "a79" })).toBeInTheDocument();
    //: 滚过去了:头和网格之间画上分隔线。
    expect(scroller).toHaveAttribute("data-scrolled", "true");
  });
});

describe("状态", () => {
  it("还在取:和格子一样大的骨架,不是一个圈", () => {
    mount({ pending: true });
    const loading = screen.getByRole("status");
    expect(loading).toHaveAttribute("aria-busy", "true");
    expect(loading.querySelectorAll(".skeleton").length).toBeGreaterThan(10);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("空着说调用方给的那句;读不出来能重试", () => {
    const onRetry = vi.fn();
    mount({ empty: { icon: null, title: "没有匹配的内容", body: "试试其他关键词" } });
    expect(screen.getByText("没有匹配的内容")).toBeInTheDocument();
    cleanup();
    mount({ error: "连不上", onRetry });
    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("画到最后几行就要下一页;下一页在路上时底下转圈", async () => {
    const onReachEnd = vi.fn();
    const { rerender } = mount({ items: [asset("a"), asset("b")], onReachEnd });
    expect(onReachEnd).toHaveBeenCalled();
    rerender(
      <AssetGridPicker
        open
        onOpenChange={() => {}}
        title="从素材库挑一份"
        searchLabel="按名字找"
        query=""
        onQueryChange={() => {}}
        items={[asset("a"), asset("b")]}
        onActivate={() => {}}
        empty={{ icon: null, title: "" }}
        loadingMore
      />,
    );
    await act(async () => {});
    expect(screen.getByRole("status")).toHaveTextContent("pageLoading");
  });
});
