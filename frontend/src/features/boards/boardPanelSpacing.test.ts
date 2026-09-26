import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";

const HERE = path.dirname(new URL(import.meta.url).pathname);
//: 格子下面那几块面板(生成、写、念、截、工具)的浮窗都由壳摆(BoardComposerShell,见 composerShell.test)。
const PANELS = ["BoardCanvas.tsx", "BoardComposerShell.tsx"];

describe("画布节点上下浮层间距", () => {
  it("采用兼顾类型标签与下方面板的 24px 间距", () => {
    expect(BOARD_NODE_PANEL_OFFSET).toBe(24);
  });

  it("所有浮层共用同一个节点边框间距", () => {
    for (const file of PANELS) {
      const source = fs.readFileSync(path.join(HERE, file), "utf8");
      expect(source, file).toContain("offset={BOARD_NODE_PANEL_OFFSET}");
      expect(source, file).not.toMatch(/offset=\{(?:12|32)\}/);
    }
  });
});
