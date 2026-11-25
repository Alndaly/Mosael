#!/usr/bin/env node
/** 开发态监听 native/macos-island,改 Swift 后重新编译;非 macOS 保持进程存活,不拖垮 concurrently。 */
import { spawnSync } from "node:child_process";
import { watch } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const nativeDir = join(root, "native", "macos-island");
const build = () => {
  const result = spawnSync(process.execPath, [join(root, "scripts", "build-macos-island.mjs")], { stdio: "inherit" });
  if (result.status !== 0) console.warn("[watch:macos-island] build failed; keeping the previous binary");
};

build();
if (process.platform !== "darwin") {
  console.log("[watch:macos-island] not macOS; no watcher needed");
  setInterval(() => {}, 1_000_000_000);
} else {
  let timer = null;
  watch(nativeDir, { recursive: true }, (_event, filename) => {
    if (filename && !filename.endsWith(".swift")) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(build, 200);
  });
  console.log(`[watch:macos-island] watching ${nativeDir}`);
}
