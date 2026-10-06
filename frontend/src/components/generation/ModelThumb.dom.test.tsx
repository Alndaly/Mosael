/** @vitest-environment jsdom */

/**
 * 模型文件的缩略图:卡片、列表、下拉要宿主缩好的缩略图,详情页才要原图;图没载好之前一直是透明的,取不到就直接换成
 * 按目录分的占位 —— 不会先闪一帧「碎图」(浏览器给取不到的图画的图标加替代文字)。
 */

import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  modelPreviewUrl: (instance: string, folder: string, name: string) => `preview://${instance}/${folder}/${name}`,
  modelThumbnailUrl: (instance: string, folder: string, name: string) => `thumbnail://${instance}/${folder}/${name}`,
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { ModelThumb } from "./ModelThumb";

afterEach(cleanup);

const lora = { folder: "loras", name: "style.safetensors", has_preview: true };

/** 看得见的图:在 DOM 里、而且不是透明的(载好之前带着 opacity-0,载好了由 data-loaded 换成不透明)。 */
const visibleImg = (root: HTMLElement) => {
  const img = root.querySelector("img");
  return img && img.hasAttribute("data-loaded") ? img : null;
};

it("默认要缩略图,详情页的大图(full)要原图", () => {
  const { container, rerender } = render(<ModelThumb instanceId="i1" model={lora} />);
  expect(container.querySelector("img")!.getAttribute("src")).toBe("thumbnail://i1/loras/style.safetensors");
  rerender(<ModelThumb instanceId="i1" model={lora} full />);
  expect(container.querySelector("img")!.getAttribute("src")).toBe("preview://i1/loras/style.safetensors");
});

it("载好之前是透明的(框照样占着位置),载好了淡入", () => {
  const { container } = render(<ModelThumb instanceId="i1" model={lora} className="aspect-[3/4] w-full" />);
  const img = container.querySelector("img")!;
  expect(visibleImg(container)).toBeNull();
  expect(img.classList.contains("opacity-0")).toBe(true);
  expect(img.classList.contains("aspect-[3/4]")).toBe(true);
  expect(img.getAttribute("loading")).toBe("lazy");
  expect(img.getAttribute("decoding")).toBe("async");
  fireEvent.load(img);
  expect(visibleImg(container)).toBe(img);
  expect(img.className).toContain("data-[loaded]:opacity-100");
});

it("取不到:没有哪一刻是看得见的碎图 —— 直接换成按目录分的占位,并告诉调用处", () => {
  const onFailed = vi.fn();
  const { container } = render(<ModelThumb instanceId="i1" model={lora} onFailed={onFailed} />);
  expect(visibleImg(container)).toBeNull();
  expect(container.querySelector("img")!.classList.contains("opacity-0")).toBe(true);
  fireEvent.error(container.querySelector("img")!);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("[data-placeholder='loras']")).toBeTruthy();
  expect(onFailed).toHaveBeenCalledTimes(1);
});

it("同一枚换了文件(下拉的触发器):上一个文件取不到、载好了,都不带到下一个", () => {
  const { container, rerender } = render(<ModelThumb instanceId="i1" model={lora} compact />);
  fireEvent.error(container.querySelector("img")!);
  expect(container.querySelector("[data-placeholder]")).toBeTruthy();
  rerender(<ModelThumb instanceId="i1" model={{ ...lora, name: "other.safetensors" }} compact />);
  const img = container.querySelector("img")!;
  expect(img.getAttribute("src")).toBe("thumbnail://i1/loras/other.safetensors");
  expect(visibleImg(container)).toBeNull();
  fireEvent.load(img);
  rerender(<ModelThumb instanceId="i1" model={{ ...lora, name: "third.safetensors" }} compact />);
  expect(visibleImg(container)).toBeNull();
});

it("预览图从哪来变了:之前没取到的换回图再取一次;载好的那张照样看得见(同一个地址,浏览器不会再发 load)", () => {
  //: 「在 Civitai 上找」刚找到一张示例图:地址没变,之前取不到的这回去取
  const { container, rerender } = render(<ModelThumb instanceId="i1" model={{ ...lora, preview_origin: "" }} full />);
  fireEvent.error(container.querySelector("img")!);
  expect(container.querySelector("img")).toBeNull();
  rerender(<ModelThumb instanceId="i1" model={{ ...lora, preview_origin: "civitai" }} full />);
  const img = container.querySelector("img")!;
  expect(img.getAttribute("src")).toBe("preview://i1/loras/style.safetensors");
  fireEvent.load(img);
  expect(visibleImg(container)).toBe(img);
  //: 「存为预览图」:来源从 Civitai 变成那台服务器,地址和 <img> 都没变 —— 不能因此变回透明
  rerender(<ModelThumb instanceId="i1" model={{ ...lora, preview_origin: "server" }} full />);
  expect(container.querySelector("img")).toBe(img);
  expect(visibleImg(container)).toBe(img);
});

it("没有预览图:一开始就是占位,不去要图", () => {
  const { container } = render(<ModelThumb instanceId="i1" model={{ ...lora, has_preview: false }} />);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("[data-placeholder='loras']")?.textContent).toBe("loras");
});

it("四档:清晰不糊;轻度、重度两种糊法,悬停 / 聚焦到外层时看清;不显示的不去取图,画目录图标加一枚眼睛", () => {
  const { container, rerender } = render(<ModelThumb instanceId="i1" model={lora} />);
  expect(container.querySelector("img")!.getAttribute("data-treatment")).toBe("clear");
  expect(container.querySelector("img")!.className).not.toContain("blur");
  rerender(<ModelThumb instanceId="i1" model={lora} treatment="light" />);
  expect(container.querySelector("img")!.className).toContain("blur-sm");
  expect(container.querySelector("img")!.className).toContain("group-hover/thumb:blur-none");
  rerender(<ModelThumb instanceId="i1" model={lora} treatment="heavy" />);
  expect(container.querySelector("img")!.className).toContain("blur-xl");
  rerender(<ModelThumb instanceId="i1" model={lora} treatment="hidden" compact />);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("[data-placeholder='loras'][data-hidden-preview]")).toBeTruthy();
  //: 本来就没有预览图的:照旧是目录图标,不说「已隐藏」
  rerender(<ModelThumb instanceId="i1" model={{ ...lora, has_preview: false }} treatment="hidden" />);
  expect(container.querySelector("[data-hidden-preview]")).toBeNull();
});
