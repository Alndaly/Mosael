#!/usr/bin/env node
/**
 * 抓取随 App 分发的独立 CPython → build/python/。
 *
 * 声音克隆的两个引擎(f5-tts / fish-speech)需要一个真 Python 来建 venv 并装依赖,而打包版的
 * 后端是 PyInstaller 冻结二进制、`sys.executable` 指向它自己,建不了 venv。所以随包带一个
 * 解释器,由 electron/main.cjs 经 MOSAEL_TTS_BASE_PYTHON 指给后端。
 *
 * **只带解释器(~40MB),不带引擎依赖**:torch + torchaudio + transformers 实测 2.5–3.5GB,
 * 预装会把安装包从 ~700MB 顶到约 4GB,而多数用户根本不用声音克隆。重的部分在用户点「下载」
 * 时装进 ~/.mosael/tts/venv(见 backend/app/domain/tts_config.py)。
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

import { PY, TARGETS, downloadUrl, sha256File, targetFor, verifySha256 } from "./tts-python-release.mjs";

const run = promisify(execFile);
const ROOT = path.resolve(import.meta.dirname, "..");
const OUT = path.join(ROOT, "build", "python");

const key = `${process.platform}-${process.arch}`;
const target = targetFor(process.platform, process.arch);
if (!target) {
  console.error(`[tts-python] 不支持的平台 ${key};支持:${Object.keys(TARGETS).join(", ")}`);
  process.exit(1);
}
const { asset, sha256 } = target;

const interpreter = path.join(OUT, process.platform === "win32" ? "python.exe" : path.join("bin", "python3"));

async function exists(p) {
  try {
    await stat(p);
    return true;
  } catch {
    return false;
  }
}

/** 已经在的那个解释器是什么版本;不在或跑不起来返回空串。 */
async function presentVersion() {
  if (!(await exists(interpreter))) return "";
  try {
    const { stdout } = await run(interpreter, ["-c", "import sys; print(sys.version.split()[0])"]);
    return stdout.trim();
  } catch {
    return "";
  }
}

// **只看「在不在」是不够的**:换了 PY 之后,本机和 CI 缓存里那个旧解释器照样「在」,
// 于是新版本号写在这里、打进包里的却还是旧的。版本对得上才跳过。
const present = await presentVersion();
if (!process.env.FORCE && present === PY) {
  console.log(`[tts-python] 已是 ${PY},跳过:${path.relative(ROOT, interpreter)}(FORCE=1 可强制重抓)`);
  process.exit(0);
}
if (present) console.log(`[tts-python] 现有的是 ${present},换成 ${PY}`);

const url = downloadUrl(asset);
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

// **解包之前**核对 sha256:哈希钉在上游那次不可变构建上(scripts/tts-python-release.mjs)。
// 打包进 App 的这个解释器会在用户机器上跑 `-m venv` 和 pip,被换包等于把任意代码发出去;
// 而 tar 一旦解包就已经落盘了,再校验只能算事后发现。对不上就删掉压缩包并退出,不继续。
const actual = await sha256File(archive);
if (!verifySha256(actual, sha256)) {
  await rm(archive, { force: true });
  console.error(`[tts-python] sha256 不匹配:${asset}`);
  console.error(`[tts-python]   期望 ${sha256}`);
  console.error(`[tts-python]   实际 ${actual}`);
  console.error(`[tts-python] 已删除下载的压缩包,未解包。上游发布若是重打过,要同步改 scripts/tts-python-release.mjs 里的哈希。`);
  process.exit(1);
}
console.log(`[tts-python] sha256 校验通过:${sha256}`);

// 压缩包里是一层 `python/`,--strip-components=1 把它摊平到 build/python/ 下。
//
// 传**相对路径**并把 cwd 设到 OUT,而不是把 `D:\a\...` 这种绝对路径交给 tar:GNU tar(Windows
// runner 上 PATH 里通常是 Git 自带的那个)会把带冒号的路径当成远程主机规格 `host:path`,于是
// 报 `tar (child): Cannot connect to D: resolve failed` —— v0.3.0 的 Windows 构建就是这么挂的。
// 相对路径没有冒号,GNU tar 与 Windows 自带的 bsdtar 都能正确处理。
await run("tar", ["-xzf", "python.tar.gz", "--strip-components", "1"], { cwd: OUT });
await rm(archive, { force: true });

if (!(await exists(interpreter))) {
  console.error(`[tts-python] 解包后找不到解释器:${interpreter}`);
  console.error(`[tts-python] 解包内容:${(await readdir(OUT)).join(", ")}`);
  process.exit(1);
}

// 冒烟:能跑、且能建 venv(这正是它在 App 里的唯一职责)。
const { stdout } = await run(interpreter, ["-c", "import sys, venv; print(sys.version.split()[0])"]);
console.log(`[tts-python] 就绪:${path.relative(ROOT, interpreter)}(Python ${stdout.trim()},venv 可用)`);
