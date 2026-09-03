import fs from "node:fs";
import path from "node:path";

import { build } from "esbuild";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");

describe("Electron preload build", () => {
  it("loads a sandbox-compatible single-file preload in development and packaged builds", async () => {
    const rootPackage = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
    const frontendPackage = JSON.parse(fs.readFileSync(path.join(ROOT, "frontend/package.json"), "utf8"));
    const main = fs.readFileSync(path.join(ROOT, "electron/main.cjs"), "utf8");
    const releaseWorkflow = fs.readFileSync(path.join(ROOT, ".github/workflows/release.yml"), "utf8");

    expect(main).toContain('preload: path.join(__dirname, "preload.bundle.cjs")');
    expect(rootPackage.scripts["build:preload"]).toContain("electron/preload.cjs");
    expect(rootPackage.scripts["build:preload"]).toContain("electron/preload.bundle.cjs");
    expect(rootPackage.scripts["build:mac"]).toContain("build:preload");
    expect(rootPackage.scripts["dist:mac"]).toContain("build:preload");
    expect(frontendPackage.scripts["electron:dev"]).toContain("build:preload");
    expect(frontendPackage.scripts["electron:dev"]).toContain("watch:preload");
    expect(releaseWorkflow).toContain("pnpm build:preload");

    const result = await build({
      entryPoints: [path.join(ROOT, "electron/preload.cjs")],
      bundle: true,
      platform: "node",
      format: "cjs",
      external: ["electron"],
      write: false,
    });
    const bundledSource = result.outputFiles[0]?.text ?? "";

    expect(bundledSource).toContain("mosael:fullscreen");
    expect(bundledSource).not.toMatch(/require\(["']\.\/ipc-contract\.cjs["']\)/);
  });
});
