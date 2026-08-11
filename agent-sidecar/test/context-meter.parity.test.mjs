/**
 * 上下文水位契约的 sidecar 一侧:跑 contracts/context-meter-cases.json。
 *
 * 后端 `backend/tests/test_context_meter_parity.py` 跑**同一份文件**。
 *
 * 为什么需要契约:同一件事(这段对话占了多少 token)有两份实现 —— 这一份决定**压不压**,
 * 后端那份(`domain/context_meter.py`)在界面上显示**还能聊多久**。后者的模块注释早就写着
 * 「两份实现必须保持同一套锚点规则,改一处就要改另一处」,而**它已经没做到**:后端补上了
 * `cacheRead`(缓存命中的部分照样占窗口),这一份没跟上。开着 prompt caching 时 input 只
 * 剩新增的一小段,于是这里看到的水位只有真实值的零头 —— 界面显示 90%,压缩迟迟不触发,
 * 直到某一轮直接超窗失败。**靠注释提醒对方不是机制。**
 *
 * 改语义时:先改 contracts/context-meter-cases.json,看着两侧一起红,再改两侧实现。
 */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..", "..");
const contract = JSON.parse(
  readFileSync(path.join(root, "contracts", "context-meter-cases.json"), "utf8"),
);

// 源码是 TS,和 compaction.test.mjs 一样用 esbuild 的 JS API 现编译再 import。
async function load(entry) {
  const outfile = path.join(mkdtempSync(path.join(tmpdir(), "parity-")), "out.mjs");
  await build({
    entryPoints: [path.join(here, "..", "src", entry)],
    outfile,
    bundle: true,
    format: "esm",
    platform: "node",
    external: ["@earendil-works/*", "undici"],
  });
  return import(pathToFileURL(outfile).href);
}

const { contextTokens, CHARS_PER_TOKEN, FALLBACK_CONTEXT_WINDOW } = await load("compaction.ts");

test("语料在,且带版本号 —— 找不到就静默跳过是最坏的结果", () => {
  assert.equal(contract.contract, "context-meter");
  assert.equal(typeof contract.version, "number");
  assert.ok(contract.cases.length > 0);
});

test("两个常量由语料说了算,不再靠两侧注释互相叮嘱", () => {
  assert.equal(CHARS_PER_TOKEN, contract.constants.chars_per_token);
  assert.equal(FALLBACK_CONTEXT_WINDOW, contract.constants.fallback_context_window);
});

for (const testCase of contract.cases) {
  test(`${testCase.name} · 上下文水位`, () => {
    const actual = contextTokens(testCase.messages);
    assert.equal(
      actual,
      testCase.context_tokens,
      `${testCase.name}\n  契约: ${testCase.context_tokens}\n  实际: ${actual}\n  用例理由: ${testCase.why ?? ""}`,
    );
  });
}
