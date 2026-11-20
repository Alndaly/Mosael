import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const { isTransientSigningFailure } = require("../scripts/sign-mac.cjs");

const testsWorkflow = readFileSync(new URL("../.github/workflows/tests.yml", import.meta.url), "utf8");
const smokeWorkflow = readFileSync(new URL("../.github/workflows/platform-smoke.yml", import.meta.url), "utf8");
const releaseWorkflow = readFileSync(new URL("../.github/workflows/release.yml", import.meta.url), "utf8");

test("主干与发布共用的 tests 工作流执行差分更新和 ratchet 文档检查", () => {
  assert.match(testsWorkflow, /electron --no-sandbox test\/differential-update\.smoke\.cjs/);
  assert.match(testsWorkflow, /python3 scripts\/sync-ratchet-docs\.py --check/);
});

test("platform-smoke 上传真实输出且 tee 不吞退出码", () => {
  assert.match(smokeWorkflow, /set -o pipefail/);
  assert.match(smokeWorkflow, /\| tee platform-smoke-report\.jsonl/);
  assert.match(smokeWorkflow, /path:\s*\|\s*\n\s*platform-smoke-report\.jsonl/);
});

test("发版草稿创建前检查滚动支持窗口", () => {
  assert.match(releaseWorkflow, /python3 scripts\/check-support-window\.py/);
  assert.ok(
    releaseWorkflow.indexOf("Verify rolling support window") < releaseWorkflow.indexOf("Create draft release"),
    "窗口检查必须排在创建 Release 之前",
  );
});

test("macOS 签名把 Apple 时间戳未回包当作瞬时失败重试", () => {
  assert.equal(isTransientSigningFailure("A timestamp was expected but was not found."), true);
  assert.equal(isTransientSigningFailure("timestamp service is not available"), true);
  assert.equal(isTransientSigningFailure("...: replacing existing signature\n...: Input/output error"), true);
  assert.equal(isTransientSigningFailure("resource fork, Finder information, or similar detritus not allowed"), false);
});
