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
import { MaskEditor } from "@/components/generation/MaskEditor";

/** 一份最小的 2D 上下文:记下它被要求做什么,像素一律给全 0。 */
class FakeContext2D {
  canvas: HTMLCanvasElement;
  fillStyle: string | CanvasGradient | CanvasPattern = "";
  globalAlpha = 1;
  /** 它被要求做过什么(断言「黑底」那一层用)。 */
  calls: string[] = [];
  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
  }
  fillRect() {
    this.calls.push(`fillRect ${String(this.fillStyle)}`);
  }
  clearRect() {}
  drawImage() {}
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
});
