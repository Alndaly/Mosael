/**
 * three r186 删掉了 PCFSoftShadowMap:写它只换来每次渲染一句「has been removed」的警告,实际按 PCFShadowMap 画,
 * 而注释和配置还以为自己在调 PCFSoft(另配了只有 VSM 才读的 blurSamples)。钉住:前端不再引用这个已删的常量。
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..", "..");

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sources(full);
    return /\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

it("不再引用 three 已经删掉的 PCFSoftShadowMap", () => {
  //: 认的是代码里的取用(`THREE.PCFSoftShadowMap`),注释里提到它不算。
  const offenders = sources(SRC).filter((file) => /\.PCFSoftShadowMap\b|import[^;]*\bPCFSoftShadowMap\b/.test(readFileSync(file, "utf8")));
  expect(offenders).toEqual([]);
});
