/**
 * 图片采集:筛掉图标与追踪像素、看文件头认格式,以及在静态测试页上跑采集脚本。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

import { IMAGE_SCAN_SCRIPT, MAX_PAGE_IMAGES, pickPageImages, sniffImage, type PageImage } from "./pageImagesCore";

const FIXTURES = join(import.meta.dirname, "fixtures", "page-tools");
const ORIGIN = "http://127.0.0.1:47011";

/** 静态测试页装进 jsdom。jsdom 不加载媒体、不实现 EME、不解码图片 —— 这几样由用例按页面声明补上。 */
function open(name: string): JSDOM {
  return new JSDOM(readFileSync(join(FIXTURES, name), "utf8"), {
    url: `${ORIGIN}/${name}`,
    runScripts: "outside-only",
  });
}

describe("图片筛选", () => {
  const image = (url: string, width: number, height: number) => ({ url, width, height, alt: "" });

  it("滤掉小图标、追踪像素、没加载完的和非 http(s) 的,同一张只留一次", () => {
    const picked = pickPageImages([
      image("https://example.com/cover.png", 640, 360),
      image("https://example.com/icon.png", 32, 32),
      image("https://example.com/pixel.gif?uid=1", 1, 1),
      image("https://example.com/lazy.jpg", 0, 0),
      image("data:image/png;base64,AAAA", 800, 800),
      image("https://example.com/cover.png#again", 640, 360),
      image("https://example.com/banner.jpg", 1200, 80),
    ]);
    expect(picked.map((one) => one.url)).toEqual(["https://example.com/cover.png"]);
  });

  it("追踪地址哪怕报了大尺寸也不要", () => {
    expect(pickPageImages([image("https://www.facebook.com/tr?id=1", 400, 400)])).toEqual([]);
  });

  it("一页最多列这么多张", () => {
    const many = Array.from({ length: MAX_PAGE_IMAGES + 30 }, (_, index) => image(`https://example.com/${index}.jpg`, 800, 600));
    expect(pickPageImages(many)).toHaveLength(MAX_PAGE_IMAGES);
  });

  it("看文件头认图片格式,不信响应头", () => {
    expect(sniffImage(Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0]))).toBe("image/png");
    expect(sniffImage(Uint8Array.from([0xff, 0xd8, 0xff, 0xe0]))).toBe("image/jpeg");
    expect(sniffImage(new TextEncoder().encode("GIF89a...."))).toBe("image/gif");
    expect(sniffImage(new TextEncoder().encode("RIFF\u0000\u0000\u0000\u0000WEBPVP8 "))).toBe("image/webp");
    expect(sniffImage(new TextEncoder().encode("<!doctype html><html>"))).toBeNull();
    expect(sniffImage(new TextEncoder().encode("<svg xmlns='http://www.w3.org/2000/svg'/>"))).toBeNull();
  });
});

describe("图片采集(静态测试页)", () => {
  it("只留够大的那张,图标和追踪像素滤掉;og:image 与正文里的同一张只留一次", () => {
    const dom = open("none.html");
    for (const image of dom.window.document.images) {
      // 真浏览器里是解码后的像素;这里按页面上声明的尺寸补。
      Object.defineProperty(image, "naturalWidth", { value: Number(image.getAttribute("width")) });
      Object.defineProperty(image, "naturalHeight", { value: Number(image.getAttribute("height")) });
    }
    const raw = dom.window.eval(IMAGE_SCAN_SCRIPT) as PageImage[];
    expect(pickPageImages(raw).map((one) => [one.url, one.width, one.height])).toEqual([[`${ORIGIN}/cover.png`, 640, 360]]);
  });
});
