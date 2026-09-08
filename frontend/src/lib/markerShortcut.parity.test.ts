/**
 * 画布标记快捷键契约的前端一侧:跑 contracts/marker-shortcut-cases.json。
 *
 * 后端 `backend/tests/test_marker_shortcut_parity.py` 跑**同一份文件**。理由见那边的说明
 * 与 contracts/README.md:两侧归出不同的串时谁都不报错,只会悄悄错开。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { normalizeCombo } from "./shortcuts";

const path = fileURLToPath(new URL("../../../contracts/marker-shortcut-cases.json", import.meta.url));
const contract = JSON.parse(readFileSync(path, "utf8")) as {
  contract: string;
  version: number;
  canonical: Array<{ name: string; why: string; raw: string; combo: string }>;
  rejected: Array<{ name: string; why: string; raw: string }>;
};

describe("marker shortcut contract", () => {
  it("is present and versioned", () => {
    expect(contract.contract).toBe("marker-shortcut");
    expect(contract.version).toBe(1);
  });

  for (const one of contract.canonical) {
    it(one.name, () => {
      expect(normalizeCombo(one.raw), one.why).toBe(one.combo);
    });
  }

  for (const one of contract.rejected) {
    it(`rejects ${one.name}`, () => {
      expect(normalizeCombo(one.raw), one.why).toBeNull();
    });
  }
});
