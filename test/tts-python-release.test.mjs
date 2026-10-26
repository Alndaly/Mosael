import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  PY,
  RELEASE,
  TARGETS,
  downloadUrl,
  sha256File,
  targetFor,
  verifySha256,
} from "../scripts/tts-python-release.mjs";

// 清单本身要能自证:四个平台一个不缺、每个哈希都是 64 位十六进制、同一个 release 里互不重复。
// 少写一个哈希时 verifySha256 会抛(而不是返回 false),但那时已经是在下载脚本里跑了;
// 这里提前在小步骤里把它钉住。
test("每个受支持平台都有资产名与 sha256", () => {
  assert.deepEqual(Object.keys(TARGETS).sort(), ["darwin-arm64", "darwin-x64", "linux-x64", "win32-x64"]);
  const seen = new Set();
  for (const [key, { asset, sha256 }] of Object.entries(TARGETS)) {
    assert.match(sha256, /^[0-9a-f]{64}$/, `${key} 的 sha256 不是 64 位小写十六进制`);
    assert.ok(asset.includes(PY), `${key} 的资产名里没有 ${PY}`);
    assert.ok(asset.includes(RELEASE), `${key} 的资产名里没有 release ${RELEASE}`);
    assert.ok(asset.endsWith("-install_only_stripped.tar.gz"), `${key} 不是 install_only_stripped 包`);
    assert.ok(!seen.has(sha256), `${key} 与其他平台共用同一个哈希`);
    seen.add(sha256);
  }
});

test("targetFor 只认四个平台,下载地址钉在这个 release 上", () => {
  assert.equal(targetFor("darwin", "arm64"), TARGETS["darwin-arm64"]);
  assert.equal(targetFor("win32", "x64"), TARGETS["win32-x64"]);
  assert.equal(targetFor("darwin", "ia32"), null);
  assert.equal(targetFor("linux", "arm64"), null);
  assert.equal(
    downloadUrl(TARGETS["linux-x64"].asset),
    `https://github.com/astral-sh/python-build-standalone/releases/download/${RELEASE}/${TARGETS["linux-x64"].asset}`,
  );
});

test("verifySha256 匹配才通过", () => {
  const good = TARGETS["darwin-arm64"].sha256;
  assert.equal(verifySha256(good, good), true);
  assert.equal(verifySha256(good.replace(/^d/, "e"), good), false);
});

// **fail closed**:期望值坏了必须抛,不能返回 false —— 返回 false 只会被某个调用方当成
// 「下次再试」,最后静默地放过一个没校验过的解释器。
test("verifySha256 对坏掉的期望值抛错", () => {
  const good = TARGETS["darwin-arm64"].sha256;
  for (const bad of [undefined, "", "todo", "0".repeat(63), "0".repeat(65), good.toUpperCase(), good.slice(1)]) {
    assert.throws(() => verifySha256(good, bad), /期望的 sha256/, String(bad));
  }
  assert.throws(() => verifySha256(undefined, good), /算出的 sha256/);
});

test("sha256File 对流式算出的哈希与 createHash 一致", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "mosael-tts-hash-"));
  try {
    const file = path.join(dir, "payload.bin");
    const payload = Buffer.from("mosael tts python archive\n".repeat(1000));
    await writeFile(file, payload);
    const expected = createHash("sha256").update(payload).digest("hex");
    assert.equal(await sha256File(file), expected);
    assert.equal(verifySha256(await sha256File(file), expected), true);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
