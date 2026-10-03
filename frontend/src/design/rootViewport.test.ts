import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(import.meta.dirname, "tokens.css"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

describe("应用根视口", () => {
  it("不让长页面把整个桌面外壳滚出窗口", () => {
    const rule = css.match(/html\s*,\s*body\s*,\s*#root\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(rule).toMatch(/height\s*:\s*100%/);
    expect(rule).toMatch(/overflow\s*:\s*hidden/);
  });
});
