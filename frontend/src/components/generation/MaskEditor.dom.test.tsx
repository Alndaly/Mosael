/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 蒙版编辑器这一格的三件事:**打开时工具都在**、**取消什么都不发**、**存下去的是不带 alpha 的灰度 PNG**
 * (ADR 0056:契约是「黑白图 + 红通道」,带 alpha 的图在插件那条路上读出来是空的 —— 静默失效)。
 *
 * jsdom 没有 canvas 2D(`getContext("2d")` 直接是 null,`ImageData` 也不存在),所以这里按**平台**打桩:
 * 一个最小的假 ctx + 一个返回真 Blob 的 toBlob。生产代码不为测试改语义 —— 拿不到 2D 上下文时它本来就
 * 只是画不出东西(见 MaskEditor 的说明),导出这条路照走。
 */

vi.mock("@/api/domains/assets", () => ({
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  importAsset: vi.fn(),
}));

import { importAsset, type Asset } from "@/api/domains/assets";
import { PreferencesProvider } from "@/app/preferences";
import { drawMaskView, MaskEditor } from "@/components/generation/MaskEditor";
import { MASK_TINT_DIM, maskViewLayers } from "@/lib/maskPixels";

/** 一份最小的 2D 上下文:记下它被要求做什么,像素一律给全 0。 */
class FakeContext2D {
  canvas: HTMLCanvasElement;
  fillStyle: string | CanvasGradient | CanvasPattern = "";
  globalAlpha = 1;
  globalCompositeOperation: GlobalCompositeOperation = "source-over";
  /** 它被要求做过什么(断言「黑底」那一层、以及合成的顺序用)。 */
  calls: string[] = [];
  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
  }
  fillRect() {
    this.calls.push(`fillRect ${String(this.fillStyle)}`);
  }
  clearRect() {
    this.calls.push("clearRect");
  }
  /** 叠上去的那一下:**顺序 + 混合方式 + 当时的 alpha**,这三样就是合成的全部。 */
  drawImage() {
    this.calls.push(`drawImage ${this.globalCompositeOperation} ${this.globalAlpha}`);
  }
  beginPath() {}
  arc() {}
  ellipse() {}
  fill() {}
  createRadialGradient() {
    return { addColorStop() {} } as unknown as CanvasGradient;
  }
  createImageData(width: number, height: number) {
    return { width, height, data: new Uint8ClampedArray(width * height * 4) } as ImageData;
  }
  getImageData(_x: number, _y: number, width: number, height: number) {
    return this.createImageData(width, height);
  }
  putImageData() {}
}

/** 一张画布一个上下文(真环境就是这样;测试要回头查那张画布被要求画过什么)。 */
const contexts = new WeakMap<HTMLCanvasElement, FakeContext2D>();
function contextOf(canvas: HTMLCanvasElement): FakeContext2D {
  const found = contexts.get(canvas);
  if (found) return found;
  const created = new FakeContext2D(canvas);
  contexts.set(canvas, created);
  return created;
}

/** 被 toBlob 导出的那张画布(见下面那条断言:它必须不是看得见的那张)。 */
let exported: HTMLCanvasElement | null = null;

beforeAll(() => {
  HTMLCanvasElement.prototype.getContext = function getContext(this: HTMLCanvasElement) {
    return contextOf(this);
  } as unknown as typeof HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.toBlob = function toBlob(this: HTMLCanvasElement, callback: BlobCallback, type?: string) {
    exported = this;
    callback(new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], { type: type ?? "image/png" }));
  };
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
});

//: 底图是 fetch 回来的(见 MaskEditor 文件头):这里让它当场失败,测试不碰网;底图读不到编辑器照样能用。
beforeEach(() => {
  globalThis.fetch = vi.fn(() => Promise.reject(new Error("offline"))) as never;
  exported = null;
  vi.mocked(importAsset).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  //: 按平台打桩的那几条(Image / ResizeObserver)自己收回去 —— 下一条用例不该看见它们。
  vi.unstubAllGlobals();
});

const SOURCE = { assetId: "src-1", name: "scene.png" };
const SAVED = { id: "mask-9", name: "蒙版 · scene.png" } as Asset;

function mount(props: Partial<React.ComponentProps<typeof MaskEditor>> = {}) {
  const onOpenChange = vi.fn();
  const onDone = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PreferencesProvider>
        <MaskEditor
          open
          onOpenChange={onOpenChange}
          workspaceId="w1"
          source={SOURCE}
          onDone={onDone}
          {...props}
        />
      </PreferencesProvider>
    </QueryClientProvider>,
  );
  return { onOpenChange, onDone };
}

describe("蒙版编辑器", () => {
  it("打开时工具条在:四种工具、撤销重做清空反选、羽化和从底图起手", () => {
    mount();
    expect(screen.getByRole("dialog", { name: "画蒙版" })).toBeTruthy();
    for (const tool of [["笔刷"], ["橡皮"], ["矩形"], ["椭圆"]]) {
      expect(screen.getByRole("radio", { name: tool[0] })).toBeTruthy();
    }
    for (const action of ["撤销", "重做", "清空", "反选", "羽化", "按亮度初始化", "按 alpha 初始化", "存成蒙版", "取消"]) {
      expect(screen.getByRole("button", { name: action }), action).toBeTruthy();
    }
    //: 画布也在(它是给人画的那一块)。
    expect(screen.getByLabelText("蒙版画布")).toBeTruthy();
  });

  it("取消:关掉弹窗,一个请求都不发", async () => {
    const { onOpenChange } = mount();
    screen.getByRole("button", { name: "取消" }).click();
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(importAsset).not.toHaveBeenCalled();
  });

  it("保存:交上去的是一张 PNG File,名字带来源;成功之后回调拿到那份素材", async () => {
    vi.mocked(importAsset).mockResolvedValue(SAVED);
    const { onDone } = mount();

    screen.getByRole("button", { name: "存成蒙版" }).click();

    await waitFor(() => expect(importAsset).toHaveBeenCalledTimes(1));
    const params = vi.mocked(importAsset).mock.calls[0][0];
    expect(params.workspaceId).toBe("w1");
    expect(params.file).toBeInstanceOf(File);
    expect(params.file.type).toBe("image/png");
    expect(params.file.name).toBe("mask.png");
    //: 名字带来源(ADR 0056 的代价那一节:素材会变多,靠名字认得出来是哪张图的蒙版)。
    expect(params.name).toBe("蒙版 · scene.png");
    //: 可取消:signal 传下去了(关弹窗 = 不等它了)。
    expect(params.signal).toBeInstanceOf(AbortSignal);

    //: 交出去的是**离屏的那张蒙版**,不是看得见的那张:底图只画在看得见的那张上,
    //: 所以导出的图里不可能有它(ADR 0056 决定 1)。
    const view = screen.getByLabelText("蒙版画布");
    expect(exported).not.toBe(view);
    expect(document.contains(exported)).toBe(false);
    //: 黑底那一层:导出的 PNG 每个像素都要不透明 —— 带 alpha 的图在插件那条路上读出来是空的。
    expect(contextOf(exported as HTMLCanvasElement).calls).toContain("fillRect #000000");

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(SAVED));
  });

  it("打开时就有一张蒙版(继续在它上面画):也是这一套;没有底图时名字里写清楚", async () => {
    //: ADR 0056 决定 5:不引入「蒙版文档」——第一次保存就是那张 PNG,要改就在它上面继续画。
    vi.mocked(importAsset).mockResolvedValue(SAVED);
    mount({ source: null, initial: { assetId: "mask-0", name: "旧的蒙版" } });

    screen.getByRole("button", { name: "存成蒙版" }).click();

    await waitFor(() => expect(importAsset).toHaveBeenCalledTimes(1));
    expect(vi.mocked(importAsset).mock.calls[0][0].name).toBe("蒙版 · 没有底图");
  });

  it("上传期间保存键在转圈;这时取消能把它停下", async () => {
    const captured: { signal?: AbortSignal }[] = [];
    vi.mocked(importAsset).mockImplementation((params) => {
      captured.push({ signal: params.signal });
      return new Promise<Asset>(() => undefined);
    });
    mount();

    screen.getByRole("button", { name: "存成蒙版" }).click();
    const save = screen.getByRole("button", { name: "存成蒙版" });

    await waitFor(() => expect(save.getAttribute("aria-busy")).toBe("true"));
    screen.getByRole("button", { name: "取消" }).click();
    await waitFor(() => expect(captured[0]?.signal?.aborted).toBe(true));
  });

  it("没有底图时「从底图起手」按不动 —— 没有像素可以读", async () => {
    mount({ source: null });
    const luminance = screen.getByRole("button", { name: "按亮度初始化" });
    await waitFor(() => expect(luminance.hasAttribute("disabled")).toBe(true));
    expect(screen.getByRole("button", { name: "按 alpha 初始化" }).hasAttribute("disabled")).toBe(true);
  });

  it("存不上时把后端那句话照实说出来(一行档,不是一行手写红字)", async () => {
    vi.mocked(importAsset).mockRejectedValue(new Error("磁盘满了"));
    mount();

    screen.getByRole("button", { name: "存成蒙版" }).click();

    expect(await screen.findByText("磁盘满了")).toBeTruthy();
  });

  /**
   * 可见那张画布的合成。蒙版是**不透明**的黑底 + 白笔迹,`source-over` 整张盖在底图上就是一块黑板:
   * 维护者看到的就是「清空之后底图也没了、反选之后图变成灰的」。这里断言**执行的顺序与 alpha**
   * (真实像素另有 Chromium 里的探针),也就是那个 bug 的形状不会再回来。
   */
  it("看得见的那张画布:底图先画,蒙版的两层后叠 —— 没有哪一下是把蒙版整张盖上去", () => {
    const view = document.createElement("canvas");
    const mask = document.createElement("canvas");
    const underlay = document.createElement("canvas");
    const scratch = document.createElement("canvas");
    const ctx = contextOf(view);
    //: 假 ctx 只记下"被要求画了什么",不是真的 2D 上下文(jsdom 里也没有);类型上过一道桥。
    const draw = (showUnderlay: boolean) =>
      drawMaskView(ctx as unknown as CanvasRenderingContext2D, {
        plan: maskViewLayers({ hasUnderlay: true, showUnderlay }),
        mask,
        underlay,
        scratch,
        width: 8,
        height: 8,
      });

    draw(true);
    expect(ctx.calls).toEqual([
      "clearRect",
      "drawImage source-over 1", // 底图:原样在下面
      `drawImage multiply ${MASK_TINT_DIM}`, // 画过的地方压暗
      "drawImage lighter 1", // 画过的地方着蒙版色
    ]);
    //: 这一条是那个 bug 的形状:最后一次 drawImage 是蒙版自己、alpha 1 —— 前两次全被它抹掉。
    expect(ctx.calls[ctx.calls.length - 1]).not.toBe("drawImage source-over 1");
    //: `difference` / `multiply` 是铺派生层用的,不该落到可见的那张上(落上去就是把底图算没了)。
    expect(ctx.calls.filter((call) => call.includes("difference"))).toEqual([]);

    ctx.calls.length = 0;
    draw(false);
    expect(ctx.calls).toEqual(["clearRect", "drawImage source-over 1"]);
  });

  it("「反选」重画的是同一条路:可见画布先清、再按层表叠,不是另找一处自己拼一遍", () => {
    mount();
    const ctx = contextOf(screen.getByLabelText("蒙版画布") as HTMLCanvasElement);
    ctx.calls.length = 0;

    screen.getByRole("button", { name: "反选" }).click();

    //: 这里没有底图(测试里 fetch 是失败的),所以层表只剩蒙版本身;重点是它**走了 paint()**。
    expect(ctx.calls).toEqual(["clearRect", "drawImage source-over 1"]);
  });

  /**
   * 底图读进来那一趟:位图尺寸没变,**内容**变了,照样得重画。
   *
   * `fit()` 在位图尺寸不变时早退(那条是留给 ResizeObserver 的:尺寸没变就没有新内容),而底图读进来
   * 时盒子早被量过一次 —— 少了 rebuild 里那一次 paint,屏幕上就一直停着上一张蒙版,底图要等用户
   * 下一次动手才出现。
   *
   * jsdom 里没有版面、也没有图片加载,所以按**平台**打桩:盒子量出 320×240、ResizeObserver 当场回调
   * (真环境里是它的首次观测把位图定下来的)、fetch 给一个 blob、Image 由测试决定什么时候 onload ——
   * 底图到之前要先把画布量好、把它的记录清干净。
   */
  it("底图读进来:位图尺寸没变也会按层表重画一次(底图先、蒙版后)", async () => {
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(320);
    vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(240);
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(private readonly callback: () => void) {}
        observe() {
          this.callback();
        }
        unobserve() {}
        disconnect() {}
      },
    );
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      blob: async () => new Blob([new Uint8Array([0x89, 0x50, 0x4e, 0x47])]),
    })) as never;
    //: jsdom 的 createObjectURL 接不住 vitest 这份 Node 的 Blob(读 _bytes 直接抛,被 loadImage 吞掉)。
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:probe");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const decoded: (() => void)[] = [];
    vi.stubGlobal(
      "Image",
      class {
        naturalWidth = 64;
        naturalHeight = 64;
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        set src(_value: string) {
          decoded.push(() => this.onload?.());
        }
      },
    );

    mount();
    const view = screen.getByLabelText("蒙版画布") as HTMLCanvasElement;
    const ctx = contextOf(view);
    //: 位图先按盒子的尺寸量好(首次观测那一趟)。
    await waitFor(() => expect([view.width, view.height]).toEqual([320, 240]));
    ctx.calls.length = 0;

    //: 现在让底图"解码完" —— 这一趟重铺文档,尺寸一点没变。
    await waitFor(() => expect(decoded.length).toBeGreaterThan(0));
    for (const fire of decoded) fire();
    await waitFor(() => expect(screen.getByRole("button", { name: "按亮度初始化" }).hasAttribute("disabled")).toBe(false));

    //: 屏幕上必须已经是"底图 + 要改的地方"那一套,而不是停着上一张蒙版。
    expect(ctx.calls).toEqual([
      "clearRect",
      "drawImage source-over 1",
      `drawImage multiply ${MASK_TINT_DIM}`,
      "drawImage lighter 1",
    ]);
  });
});
