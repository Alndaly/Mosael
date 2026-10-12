/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
import { MASK_TINT_DIM, MASK_TINT_TOKEN, maskViewLayers } from "@/lib/maskPixels";

/**
 * 蒙版色那个 token 与它的两套值。**名字写死在这里**:组件要是去问别的名字,替身不会给值,
 * 那几条断言就红 —— 而这个名字是 tokens.css 里真有的那一个(浅 / 深各一套,见 design/tokens.css)。
 */
const TINT_TOKEN = "--destructive";
const LIGHT_TINT = "#bd383e";
const DARK_TINT = "#f28d96";

/** 一份最小的 2D 上下文:记下它被要求做什么,像素一律给全 0。 */
class FakeContext2D {
  canvas: HTMLCanvasElement;
  fillStyle: string | CanvasGradient | CanvasPattern = "";
  globalAlpha = 1;
  globalCompositeOperation: GlobalCompositeOperation = "source-over";
  /** 它被要求做过什么(断言「黑底」那一层、以及合成的顺序用)。 */
  calls: string[] = [];
  /** `putImageData` 交出去的那几份像素 —— 蒙版的透明像素就是从这条路上写进去的。 */
  written: ImageData[] = [];
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
  putImageData(image: ImageData) {
    this.written.push(image);
  }
}

/** 一张画布一个上下文(真环境就是这样;测试要回头查那张画布被要求画过什么)。 */
const contexts = new WeakMap<HTMLCanvasElement, FakeContext2D>();
/** 建过的每一个假上下文 —— 要回头找那张**不在 DOM 里**的离屏画布(见 scratchContext)。 */
const everyContext: FakeContext2D[] = [];
function contextOf(canvas: HTMLCanvasElement): FakeContext2D {
  const found = contexts.get(canvas);
  if (found) return found;
  const created = new FakeContext2D(canvas);
  contexts.set(canvas, created);
  everyContext.push(created);
  return created;
}

/**
 * 铺派生层的那张**复用**的离屏画布(见 MaskEditor 的 maskLayer):唯一被要求铺过白底的一张 ——
 * 可见的那张只有 clearRect / drawImage,离屏蒙版铺的是黑底。
 */
function scratchContext(): FakeContext2D {
  const found = everyContext.find((ctx) => ctx.calls.includes("fillRect #ffffff"));
  if (!found) throw new Error("没有哪张画布被铺过派生层的底 —— 层表里那两层没画?");
  return found;
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
  //: 切主题的用例把 `<html>` 拨到了深色(真应用也是这么切的)—— 收回来。
  document.documentElement.classList.remove("dark");
  delete document.documentElement.dataset.theme;
  //: 上一批用例建的那些画布连上下文一起忘掉:scratchContext() 是"在**这一条**用例建过的画布里找",
  //: 攒着找的话它会摸到上一条用例那张离屏画布(实测:清了自己的记录、断言却打在别人那张上)。
  everyContext.length = 0;
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

  /**
   * 画出来的蒙版要**说得出出处**:编辑器知道自己在给哪张素材画,那就得把那一项跟着上传交给后端
   * (见后端 domain/assets/lineage)。此前这条路没有出处 —— 素材详情「来自」永远空着,从一张 AI 图
   * 画的蒙版也不会被标含 AI(`inherits_ai` 拿到的是空列表)。
   */
  it("保存:带上出处 —— 这份蒙版是从哪张素材画出来的", async () => {
    vi.mocked(importAsset).mockResolvedValue(SAVED);
    mount();

    screen.getByRole("button", { name: "存成蒙版" }).click();

    await waitFor(() => expect(importAsset).toHaveBeenCalledTimes(1));
    expect(vi.mocked(importAsset).mock.calls[0][0].derivedFrom).toEqual([{ asset_id: SOURCE.assetId, op: "mask" }]);
  });

  it("没有源素材(新建一张空蒙版):不带出处", async () => {
    vi.mocked(importAsset).mockResolvedValue(SAVED);
    mount({ source: null });

    screen.getByRole("button", { name: "存成蒙版" }).click();

    await waitFor(() => expect(importAsset).toHaveBeenCalledTimes(1));
    //: 不派生自任何一份时**一个字都不说** —— 与这条接口收出处之前的形状完全一样。
    expect(vi.mocked(importAsset).mock.calls[0][0].derivedFrom).toBeUndefined();
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
        plan: maskViewLayers({ hasUnderlay: true, showUnderlay, tint: LIGHT_TINT }),
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
    //: 位图先按**含住盒子那块矩形**量好(首次观测那一趟):文档这时还是默认的 1024²(方),
    //: 盒子 320×240 ⇒ contain 出来是 240×240(边长取盒子的高)。
    await waitFor(() => expect([view.width, view.height]).toEqual([240, 240]));
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

  /**
   * ## 蒙版色从主题来
   *
   * 维护者:「`#e5484d` 是写死的字面量(canvas 读不到 CSS 变量)—— 浅 / 深主题都同一个红 这个得改改」。
   *
   * jsdom 里一个 token 也读不出来(没有样式表),所以按**平台**打桩:`getComputedStyle` 照
   * truncate.dom.test.tsx 那样**代理真身**,只把那个 token 换掉,并按 `<html>` 上有没有 `.dark` 给浅 / 深
   * 两套值 —— 真 CSS 走的就是同一个判据(preferences.tsx 把主题写在 class 上)。**读了几次也记下来**:
   * 「按主题解析一次、缓存起来」就是看这个数会不会跟着每一帧涨。
   */
  function stubThemeToken() {
    const state = { reads: 0 };
    const real = window.getComputedStyle.bind(window);
    vi.spyOn(window, "getComputedStyle").mockImplementation((element: Element, pseudo?: string | null) => {
      const style = real(element, pseudo);
      return new Proxy(style, {
        get(target, key) {
          if (key === "getPropertyValue") {
            return (property: string) => {
              if (property !== TINT_TOKEN) return target.getPropertyValue(property);
              state.reads += 1;
              return document.documentElement.classList.contains("dark") ? DARK_TINT : LIGHT_TINT;
            };
          }
          const value = Reflect.get(target, key);
          return typeof value === "function" ? value.bind(target) : value;
        },
      });
    });
    return state;
  }

  /**
   * 让底图读得进来 —— 和「底图读进来」那条同一套平台打桩(jsdom 里没有版面、也没有图片解码):
   * 盒子量出 320×240、ResizeObserver 首次观测当场回调、fetch 给一个 blob、Image 由返回的数组决定
   * 什么时候 onload。**着色那一层只在有底图时才在层表里**,所以这一格必须先真的有一张底图。
   *
   * 注意尺寸:默认那张 64×64 的底图是**方**的,在 320×240 的盒子里 contain 出来是 240×240
   * (位图尺寸见 fit();底图到之前文档还是默认的 1024²,同样 contain 成 240×240 —— 两条一样)。
   */
  function stubUnderlayPlatform(size: { width: number; height: number } = { width: 64, height: 64 }): (() => void)[] {
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
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:probe");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    const decoded: (() => void)[] = [];
    vi.stubGlobal(
      "Image",
      class {
        naturalWidth = size.width;
        naturalHeight = size.height;
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        set src(_value: string) {
          decoded.push(() => this.onload?.());
        }
      },
    );
    return decoded;
  }

  /** 挂上,并等到底图进来(层表那三层都在画)。 */
  async function mountWithUnderlay(): Promise<HTMLCanvasElement> {
    const decoded = stubUnderlayPlatform();
    mount();
    const view = screen.getByLabelText("蒙版画布") as HTMLCanvasElement;
    await waitFor(() => expect([view.width, view.height]).toEqual([240, 240]));
    await waitFor(() => expect(decoded.length).toBeGreaterThan(0));
    for (const fire of decoded) fire();
    await waitFor(() => expect(screen.getByRole("button", { name: "按亮度初始化" }).hasAttribute("disabled")).toBe(false));
    return view;
  }

  it("主题色交给合成:着色那一层铺的就是解析出来的那个颜色,而且不是每帧去读样式", async () => {
    //: 组件问的就是 tokens.css 里那个 token(问别的名字,替身不给值,下面三条全红)。
    expect(MASK_TINT_TOKEN).toBe(TINT_TOKEN);
    const reads = stubThemeToken();
    const view = await mountWithUnderlay();

    //: 画过的那一层:底铺的就是主题给的颜色,再拿蒙版乘上去(见 MaskEditor 的 maskLayer)。
    const scratch = scratchContext();
    expect(scratch.calls).toContain(`fillRect ${LIGHT_TINT}`);

    //: 再画一帧(「反选」走的就是 paint()):颜色还是那个,而样式**一次都没再读** —— 这就是「缓存」。
    const before = reads.reads;
    expect(before, "取色发生在挂载那几帧里").toBeGreaterThan(0);
    scratch.calls.length = 0;
    screen.getByRole("button", { name: "反选" }).click();
    expect(scratch.calls).toContain(`fillRect ${LIGHT_TINT}`);
    expect(reads.reads).toBe(before);
    expect(view.width).toBe(240);
  });

  it("主题切到深色:当场重画,用的是新颜色 —— 不用等用户下一次动手", async () => {
    stubThemeToken();
    const view = await mountWithUnderlay();
    const scratch = scratchContext();
    expect(scratch.calls).toContain(`fillRect ${LIGHT_TINT}`);

    //: 真应用切主题写的就是这两样(app/preferences.tsx):`class="dark"` + `data-theme`。
    scratch.calls.length = 0;
    const visible = contextOf(view);
    visible.calls.length = 0;
    document.documentElement.classList.add("dark");
    document.documentElement.dataset.theme = "dark";

    await waitFor(() => expect(scratch.calls).toContain(`fillRect ${DARK_TINT}`));
    //: 而且是**重画**:可见那张先清了一整张再按层表叠(不是别处顺手画了一下)。
    expect(visible.calls[0]).toBe("clearRect");
    expect(scratch.calls).not.toContain(`fillRect ${LIGHT_TINT}`);
  });

  /**
   * ## 形状工具的预览会把蒙版写成透明的(维护者:「矩形 / 椭圆工具会让整块画布变灰」)
   *
   * 形状工具的每一帧都是「从按下时那份像素重来」(`restore(drag.before)`),而**按下之后底图才读进来**
   * 的话,文档会从默认的 1024² 换成源图那个尺寸(维护者的图 1624×2880)—— 那份快照就对不上了。
   * 此前 `restore` 照写不误:`createImageData` 是**零填充**的、`writeGrayscale` 只写它覆盖得到的那一段,
   * 于是剩下的像素全是 `alpha 0`。蒙版一旦有透明像素:
   *
   * - 屏幕上那两张派生层(`maskInverse` / `maskTint`)遇到透明像素会**保持底色**(`difference` /
   *   `multiply` 按源的 alpha 加权)⇒ 没画过的地方不再等于原图、**整块画布被蒙版色糊住**;
   * - **导出的 PNG 带上 alpha 通道** ⇒ 插件那条 `LoadImageMask(channel="red")` 静默什么都不重绘。
   *
   * 笔刷不走 `restore`,所以笔刷没有这个问题 —— 这正是「形状工具 vs 笔刷」的分叉点。
   *
   * 这里钉住不变量:**写进蒙版的每一份 `ImageData` 都必须每个像素 `alpha 255`**,而且那一帧**真的写了**
   * (预览仍然是「每帧重来」,不是被整张挡掉、变成一层层叠)。真 Chromium 的像素实测见报告。
   */
  it("拖动途中底图才读进来:蒙版不会被写成透明的,预览照旧每帧重来", async () => {
    //: 源图比默认文档(1024²)大 —— 文档是**长大**的,快照才会比文档短,正好踩中那一段零填充。
    const decoded = stubUnderlayPlatform({ width: 2000, height: 1500 });
    //: 拖动落点要真的算得出来:jsdom 没有版面,`docPoint` 读的是元素自己的矩形。
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 320, 240));
    //: jsdom 的指针捕获是空壳:真点下去时 `setPointerCapture` 由 Canvas 收走指针(见组件)。
    Object.assign(Element.prototype, { setPointerCapture: () => {}, releasePointerCapture: () => {}, hasPointerCapture: () => false });
    mount();
    const view = screen.getByLabelText("蒙版画布") as HTMLCanvasElement;
    await waitFor(() => expect([view.width, view.height]).toEqual([240, 240]));

    //: 选矩形,在底图还没到的时候按下 —— 这一份快照是 1024² 那张文档的。
    fireEvent.click(screen.getByRole("radio", { name: "矩形" }));
    fireEvent.pointerDown(view, { clientX: 100, clientY: 80, pointerId: 1, button: 0, buttons: 1 });

    //: 现在底图到了:文档换成 2000×1500。
    await waitFor(() => expect(decoded.length).toBeGreaterThan(0));
    for (const fire of decoded) fire();
    await waitFor(() => expect(screen.getByRole("button", { name: "按亮度初始化" }).hasAttribute("disabled")).toBe(false));

    fireEvent.pointerMove(view, { clientX: 160, clientY: 120, pointerId: 1, button: 0, buttons: 1 });
    fireEvent.pointerUp(view, { clientX: 160, clientY: 120, pointerId: 1, button: 0, buttons: 0 });

    const written = everyContext.flatMap((ctx) => ctx.written);
    expect(written.length, "这一帧真的把「按下时那份」写回去过(预览没被整张挡掉)").toBeGreaterThan(0);
    const transparent = written
      .map((image) => {
        let count = 0;
        for (let at = 3; at < image.data.length; at += 4) if (image.data[at] !== 255) count += 1;
        return `${image.width}×${image.height}: ${count}`;
      })
      .filter((line) => !line.endsWith(": 0"));
    expect(transparent, "写进蒙版的像素必须全不透明(蒙版契约:每个像素 alpha 255)").toEqual([]);
  });
  /**
   * ## 画布按原始比例(维护者:「**注意图片应该是原先的比例**」)
   *
   * 此前画布元素铺满盒子、位图也按盒子的尺寸写 —— 源图不是盒子那个比例时**被拉伸/压扁**
   * (竖幅 1624×2880 放进横幅的盒子几乎认不出来)。现在按 contain 缩:长边贴住盒子、短边按原始
   * 比例留白;**留白是弹窗自己的底色**(画布那一格不再有 `bg-black` —— 那正是"两条大黑边"的来源),
   * 矩形四条边由画布自己的 `border` 画出来。
   *
   * 这里钉的是**等比**那一件事(维护者那种竖幅图放进 320×240 的盒子):绘制矩形的宽高比 ==
   * 图的宽高比,1px 取整之内;以及"留白不是黑"。真 Chromium 的四角落点实测见报告。
   */
  it("盒子比例 ≠ 图比例:按原始比例缩进去(contain),留白不是黑", async () => {
    const decoded = stubUnderlayPlatform({ width: 1624, height: 2880 });
    mount();
    const view = screen.getByLabelText("蒙版画布") as HTMLCanvasElement;
    await waitFor(() => expect(decoded.length).toBeGreaterThan(0));
    for (const fire of decoded) fire();
    await waitFor(() => expect(screen.getByRole("button", { name: "按亮度初始化" }).hasAttribute("disabled")).toBe(false));

    //: 等比:绘制矩形的宽高比 == 图的宽高比(1px 取整之内)。拉伸的话这里差 0.7 以上。
    expect(Math.abs(view.width - view.height * (1624 / 2880)), "1px 取整之内").toBeLessThanOrEqual(1);
    //: 高占满盒子(240),宽按比例 ⇒ 元素自己也是那块矩形(CSS 尺寸是 fit() 写下去的)。
    expect(view.style.height).toBe("240px");
    expect(Number.parseInt(view.style.width, 10)).toBeLessThanOrEqual(136);
    //: 留白不是黑:画布那一格不刷黑;四条边看得到(画布自己的 border)。
    const frame = view.parentElement as HTMLElement;
    expect(frame.className).not.toContain("bg-black");
    expect(frame.className).not.toMatch(/bg-\[#0{3}/);
    expect(view.className).toContain("border");
  });
});
