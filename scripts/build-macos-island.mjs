#!/usr/bin/env node
/**
 * 编译 macOS 灵动岛的 NSPanel helper。
 *
 * 它是独立进程,不属于 Electron 主窗口;源码在 native/macos-island。
 * 只有 macOS 打包需要,其他平台直接跳过(CI 的 Windows job 不因此变红)。
 */
import { chmodSync, mkdirSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "build", "macos-island");
const out = join(outDir, "mosael-island");
const sources = [
  "IslandModels.swift",
  "IslandStore.swift",
  "IslandView.swift",
  "IslandPanel.swift",
  "main.swift",
].map((name) => join(root, "native", "macos-island", name));

if (process.platform !== "darwin") {
  console.log("macos-island: skipped (not macOS)");
  process.exit(0);
}

mkdirSync(outDir, { recursive: true });
rmSync(out, { force: true });
const result = spawnSync("xcrun", [
  "--sdk", "macosx", "swiftc",
  "-O",
  "-target", "arm64-apple-macos12.0",
  ...sources,
  "-framework", "AppKit",
  "-framework", "SwiftUI",
  "-o", out,
], { stdio: "inherit" });
if (result.status !== 0) process.exit(result.status ?? 1);
chmodSync(out, 0o755);

const version = spawnSync(out, ["--version"], { encoding: "utf8" });
if (version.status !== 0) {
  console.error("macos-island: built binary failed --version");
  process.exit(version.status ?? 1);
}
console.log(`macos-island: built ${out} (${version.stdout.trim()})`);
