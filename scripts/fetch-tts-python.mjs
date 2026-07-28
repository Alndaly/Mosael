#!/usr/bin/env node
/**
 * 抓取随 App 分发的独立 CPython → build/python/。
 *
 * 声音克隆的两个引擎(f5-tts / fish-speech)需要一个真 Python 来建 venv 并装依赖,而打包版的
 * 后端是 PyInstaller 冻结二进制、`sys.executable` 指向它自己,建不了 venv。所以随包带一个
 * 解释器,由 electron/main.cjs 经 OPEN_STUDIO_TTS_BASE_PYTHON 指给后端。
 *
 * **只带解释器(~40MB),不带引擎依赖**:torch + torchaudio + transformers 实测 2.5–3.5GB,
 * 预装会把安装包从 ~700MB 顶到约 4GB,而多数用户根本不用声音克隆。重的部分在用户点「下载」
 * 时装进 ~/.open-studio/tts/venv(见 backend/app/domain/tts_config.py)。
 *
 * 产物已在(且看着完整)则跳过,便于反复构建。设 FORCE=1 可强制重抓。
 */
import { createWriteStream } from "node:fs";
import { mkdir, rm, stat, readdir } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";

const run = promisify(execFile);
const ROOT = path.resolve(import.meta.dirname, "..");
const OUT = path.join(ROOT, "build", "python");

// python-build-standalone:预编译、可重定位的 CPython,专为"随应用分发"设计。
const RELEASE = "20250818";
const PY = "3.12.11";
const TARGETS = {
  "darwin-arm64": `cpython-${PY}+${RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz`,
  "darwin-x64": `cpython-${PY}+${RELEASE}-x86_64-apple-darwin-install_only_stripped.tar.gz`,
  "win32-x64": `cpython-${PY}+${RELEASE}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`,
  "linux-x64": `cpython-${PY}+${RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz`,
};

const key = `${process.platform}-${process.arch}`;
const asset = TARGETS[key];
if (!asset) {
  console.error(`[tts-python] 不支持的平台 ${key};支持:${Object.keys(TARGETS).join(", ")}`);
  process.exit(1);
}

const interpreter = path.join(OUT, process.platform === "win32" ? "python.exe" : path.join("bin", "python3"));

async function exists(p) {
  try {
    await stat(p);
    return true;
  } catch {
    return false;
  }
}

if (!process.env.FORCE && (await exists(interpreter))) {
  console.log(`[tts-python] 已存在,跳过:${path.relative(ROOT, interpreter)}(FORCE=1 可强制重抓)`);
  process.exit(0);
}

const url = `https://github.com/astral-sh/python-build-standalone/releases/download/${RELEASE}/${asset}`;
console.log(`[tts-python] 下载 ${asset}`);

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });

const res = await fetch(url, { redirect: "follow" });
if (!res.ok) {
  console.error(`[tts-python] 下载失败:HTTP ${res.status} ${url}`);
  process.exit(1);
}
const archive = path.join(OUT, "python.tar.gz");
await pipeline(Readable.fromWeb(res.body), createWriteStream(archive));

// 压缩包里是一层 `python/`,--strip-components=1 把它摊平到 build/python/ 下。
await run("tar", ["-xzf", archive, "-C", OUT, "--strip-components", "1"]);
await rm(archive, { force: true });

if (!(await exists(interpreter))) {
  console.error(`[tts-python] 解包后找不到解释器:${interpreter}`);
  console.error(`[tts-python] 解包内容:${(await readdir(OUT)).join(", ")}`);
  process.exit(1);
}

// 冒烟:能跑、且能建 venv(这正是它在 App 里的唯一职责)。
const { stdout } = await run(interpreter, ["-c", "import sys, venv; print(sys.version.split()[0])"]);
console.log(`[tts-python] 就绪:${path.relative(ROOT, interpreter)}(Python ${stdout.trim()},venv 可用)`);
