/**
 * 采集页面图片:素材名怎么起。
 */
import { expect, it } from "vitest";

import { imageName } from "./imageActions";

it("页面图片:有 alt 用 alt,没有用文件名", () => {
  expect(imageName("https://cdn.example.com/a/cover.png?w=1", "封面")).toBe("封面");
  expect(imageName("https://cdn.example.com/a/%E5%B0%81%E9%9D%A2.png?w=1", " ")).toBe("封面.png");
});
