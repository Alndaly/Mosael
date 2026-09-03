import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { clipAppearancePayload, readClipAppearance } from "./clipAppearance";

const path = fileURLToPath(new URL("../../../../contracts/clip-appearance-cases.json", import.meta.url));
const contract = JSON.parse(readFileSync(path, "utf8")) as {
  contract: string;
  version: number;
  cases: Array<{ name: string; effects: unknown; expected: unknown }>;
};

describe("clip appearance contract", () => {
  it("is present and versioned", () => {
    expect(contract.contract).toBe("clip-appearance");
    expect(contract.version).toBe(1);
  });

  for (const testCase of contract.cases) {
    it(testCase.name, () => {
      expect(clipAppearancePayload(readClipAppearance(testCase.effects))).toEqual(testCase.expected);
    });
  }
});
