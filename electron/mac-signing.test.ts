import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { afterAll, describe, expect, it } from "vitest";
const { needsCodeSignature } = createRequire(import.meta.url)("../scripts/sign-mac.cjs");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-signing-test-"));
afterAll(() => fs.rmSync(temporary, { recursive: true, force: true }));
function file(name: string, content: Buffer) {
  const target = path.join(temporary, name);
  fs.writeFileSync(target, content);
  return target;
}
describe("macOS signing scope", () => {
  it("signs native executables regardless of filename, including universal binaries", () => {
    for (const magic of ["cffaedfe", "feedface", "cafebabe", "bfbafeca"]) {
      expect(needsCodeSignature(file(`${magic}.dat`, Buffer.from(magic + "00000000", "hex")))).toBe(true);
    }
    expect(needsCodeSignature(temporary)).toBe(true);
  });
  it("leaves non-native resources inside the bundle's resource seal", () => {
    for (const [name, content] of [
      ["codec.wasm", "0061736d01000000"],
      ["font.ttf", "00010000000a0000"],
      ["python.pyc", "a70d0d0a00000000"],
      ["windows.exe", "4d5a900003000000"],
      ["empty", ""],
    ]) expect(needsCodeSignature(file(name, Buffer.from(content, "hex")))).toBe(false);
  });
  it("does not silently skip files that cannot be inspected", () => {
    expect(() => needsCodeSignature(path.join(temporary, "missing"))).toThrow();
  });
});
