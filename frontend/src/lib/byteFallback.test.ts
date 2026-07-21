import { describe, expect, it } from "vitest";

import { decodeByteFallback } from "./byteFallback";

describe("decodeByteFallback", () => {
  it("reassembles a llama.cpp byte-fallback emoji", () => {
    // <0xF0><0x9F><0x97><0x84> 是 🗄 的 UTF-8 四字节——线上截图里的原样形态。
    expect(decodeByteFallback("3. <0xF0><0x9F><0x97><0x84> 什么时候用哪个工具?")).toBe("3. 🗄 什么时候用哪个工具?");
  });

  it("decodes multiple runs and mixed text", () => {
    expect(decodeByteFallback("<0xE2><0x9C><0x85> 完成 <0xF0><0x9F><0x8E><0xAC>")).toBe("✅ 完成 🎬");
  });

  it("leaves an invalid byte run untouched rather than corrupting it", () => {
    expect(decodeByteFallback("坏串 <0xF0><0x28>")).toBe("坏串 <0xF0><0x28>");
  });

  it("passes ordinary text through unchanged", () => {
    const text = "普通文本,包含 <code> 和 0x1F 但不是字节 token";
    expect(decodeByteFallback(text)).toBe(text);
  });
});
