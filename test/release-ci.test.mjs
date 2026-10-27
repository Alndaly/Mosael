import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const testsWorkflow = readFileSync(new URL("../.github/workflows/tests.yml", import.meta.url), "utf8");
const smokeWorkflow = readFileSync(new URL("../.github/workflows/platform-smoke.yml", import.meta.url), "utf8");

test("主干与发布共用的 tests 工作流执行差分更新和 ratchet 文档检查", () => {
  assert.match(testsWorkflow, /electron --no-sandbox test\/differential-update\.smoke\.cjs/);
  assert.match(testsWorkflow, /python3 scripts\/sync-ratchet-docs\.py --check/);
});

test("platform-smoke 上传真实输出且 tee 不吞退出码", () => {
  assert.match(smokeWorkflow, /set -o pipefail/);
  assert.match(smokeWorkflow, /\| tee platform-smoke-report\.jsonl/);
  assert.match(smokeWorkflow, /path:\s*\|\s*\n\s*platform-smoke-report\.jsonl/);
});
