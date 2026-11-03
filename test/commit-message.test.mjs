import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const script = new URL("../scripts/check_commit_message.py", import.meta.url).pathname;

function check(message) {
  const dir = mkdtempSync(join(tmpdir(), "mosael-commit-msg-"));
  const file = join(dir, "COMMIT_EDITMSG");
  writeFileSync(file, message);
  return spawnSync("python3", [script, file], { encoding: "utf8" });
}

const valid = `feat(engines): 删除已安装的引擎

## 背景

用户装完 Demucs 后没有删除入口。

## 改动

- 增加删除接口与管理页入口。

## 验证

- 后端定向测试通过。
`;

test("完整的提交信息通过", () => {
  const result = check(valid);
  assert.equal(result.status, 0, result.stderr);
});

test("只有标题的提交被拒绝", () => {
  const result = check("fix(ai): 修一个错误\n");
  assert.equal(result.status, 1);
  assert.match(result.stderr, /缺少「## 背景」/);
});

test("空的一节也会被拒绝", () => {
  const result = check("fix(ai): 修一个错误\n\n## 背景\n\n## 改动\n改了。\n\n## 验证\n过了。\n");
  assert.equal(result.status, 1);
  assert.match(result.stderr, /「## 背景」一节是空的/);
});

test("合并提交与 autosquash 标题跳过正文检查", () => {
  for (const subject of ["Merge branch 'main'", "fixup! feat: 上一版", "squash! fix: 上一版"]) {
    const result = check(`${subject}\n`);
    assert.equal(result.status, 0, `${subject}: ${result.stderr}`);
  }
});
