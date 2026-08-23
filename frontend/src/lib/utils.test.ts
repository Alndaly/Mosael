import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn 认识我们自己的字号", () => {
  it("字号和文字颜色能共存 —— 它们不是同一组", () => {
    // tailwind-merge 不认识 `ui-xs` 时,会按前缀把两者判成 text-color 冲突并丢掉字号。
    // 真机症状:同一行「已完成」12.5px、「耗时」10.5px,源码里写的却是同一个 text-ui-xs。
    const merged = cn("text-ui-xs text-muted-foreground");
    expect(merged).toContain("text-ui-xs");
    expect(merged).toContain("text-muted-foreground");
  });

  it("四档字号都登记过", () => {
    for (const size of ["ui-2xs", "ui-xs", "ui-sm", "ui-md"]) {
      expect(cn(`text-${size} text-destructive`)).toContain(`text-${size}`);
    }
  });

  it("同组仍然后来居上 —— 登记不是把冲突关掉", () => {
    // 两个字号相遇,后写的赢(这才是 cn 存在的意义);颜色同理。
    expect(cn("text-ui-xs", "text-ui-md")).toBe("text-ui-md");
    expect(cn("text-muted-foreground", "text-destructive")).toBe("text-destructive");
  });
});
