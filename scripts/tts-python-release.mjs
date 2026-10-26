/**
 * 随包分发的 CPython 的版本、资产名与 sha256。
 *
 * 抽成模块是为了两件事:**下载脚本**和**单元测试**用同一份清单。清单只在这里写一次,
 * 测试在不联网、不解包的前提下就能钉住「每个平台都有哈希、每个哈希都是 64 位十六进制」,
 * 以及「哈希对不上时必须拒绝」—— 这段判断如果只活在 fetch-tts-python.mjs 的顶层流程里,
 * 就没法在无网络的 CI 里被验证。
 *
 * **升 PY / RELEASE 时**:改这两行,再从该 release 的
 * `.../releases/download/<RELEASE>/SHA256SUMS` 里抄四个 `*-install_only_stripped.tar.gz`
 * 的哈希(不要用本地算出来的值,那等于把「我下载到的这份」当成真相)。某个平台漏了哈希,
 * 在它上面打包时会在下载后校验那一步抛错退出,而不是静默放过。
 */
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { pipeline } from "node:stream/promises";

// python-build-standalone:预编译、可重定位的 CPython,专为"随应用分发"设计。
export const RELEASE = "20261001";

// **3.13,不是 3.14。** 这个解释器建的 venv 要装转写引擎 whisperx,而它到最新的 3.8.6 为止都声明
// Requires-Python <3.14 —— 3.14 上 pip 直接找不到能装的版本。其余引擎(f5-tts、fish-speech、
// funasr、demucs)3.14 都装得上。whisperx 放开 3.14 之后再升;后端自己早已是 3.14,它不 import whisperx。
export const PY = "3.13.16";

/**
 * 每个平台的资产名与 sha256。
 *
 * 哈希取自该 release 的 `SHA256SUMS`(与资产同一次不可变的上游构建),不是本地算出来的 ——
 * 本地算等于把「我下载到的这份」当成了真相,中间被换包也验不出来。
 */
export const TARGETS = {
  "darwin-arm64": {
    asset: `cpython-${PY}+${RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz`,
    sha256: "d00669acb53c1b014f1fcf5eaea740d8e45c3aff4b1e0244dc0f8697fb211a82",
  },
  "darwin-x64": {
    asset: `cpython-${PY}+${RELEASE}-x86_64-apple-darwin-install_only_stripped.tar.gz`,
    sha256: "a88bef59d9dd61ba4210772cce57a4b4cb963aa745ab956f7cc79ba60f9e2523",
  },
  "win32-x64": {
    asset: `cpython-${PY}+${RELEASE}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz`,
    sha256: "c402eb9a35aba90de319bbc87d23e6d887eca1551a05cfa80775f92dcf3ebc08",
  },
  "linux-x64": {
    asset: `cpython-${PY}+${RELEASE}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz`,
    sha256: "ffcb50e716789d1a6e1db5e745d4d194ac8ed9b015ccf5eabcaccb179a25e4a8",
  },
};

export function targetFor(platform, arch) {
  return TARGETS[`${platform}-${arch}`] ?? null;
}

export function downloadUrl(asset, release = RELEASE) {
  return `https://github.com/astral-sh/python-build-standalone/releases/download/${release}/${asset}`;
}

const SHA256_HEX = /^[0-9a-f]{64}$/;

/**
 * 校验下载到的字节的 sha256。
 *
 * **收不到合法期望值时抛,不返回 false**:空串 / 占位符 / 少一位都会被当成「校验失败」而静默
 * 落到某个分支去;期望值本身坏了必须当场炸,否则这道闸就成了摆设。
 */
export function verifySha256(actualHex, expectedHex) {
  if (typeof expectedHex !== "string" || !SHA256_HEX.test(expectedHex)) {
    throw new Error(`期望的 sha256 不是 64 位小写十六进制:${JSON.stringify(expectedHex)}`);
  }
  if (typeof actualHex !== "string" || !SHA256_HEX.test(actualHex)) {
    throw new Error(`算出的 sha256 不是 64 位小写十六进制:${JSON.stringify(actualHex)}`);
  }
  return actualHex === expectedHex;
}

/** 流式计算文件哈希:资产 ~40MB,不整份读进内存。 */
export async function sha256File(file) {
  const hash = createHash("sha256");
  await pipeline(createReadStream(file), hash);
  return hash.digest("hex");
}
