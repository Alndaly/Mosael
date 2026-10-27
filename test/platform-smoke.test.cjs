const assert = require("node:assert/strict");
const test = require("node:test");

const { runAll } = require("../scripts/platform-smoke.cjs");

function run(children) {
  const output = [];
  const original = console.log;
  console.log = (line) => output.push(JSON.parse(line));
  try {
    const code = runAll(Object.keys(children), (_executable, args) => {
      const id = args[args.indexOf("--platform") + 1];
      return { encoding: "utf8", ...children[id] };
    });
    return { code, summary: output[0], results: output.slice(1) };
  } finally {
    console.log = original;
  }
}

test("子进程非零退出时,即使留下成功 JSON 也必须汇总为失败", () => {
  const result = run({
    x: { status: 1, stdout: '{"platform":"x","ok":true}\n', stderr: "renderer crashed" },
  });
  assert.equal(result.code, 1);
  assert.equal(result.summary.total, 1);
  assert.equal(result.summary.failed, 1);
  assert.equal(result.results[0].platform, "x");
  assert.equal(result.results[0].ok, false);
  assert.equal(result.results[0].exitCode, 1);
  assert.match(result.results[0].failure, /1/);
});

test("子进程超时且没有完成冒烟时,保留失败事实", () => {
  const result = run({
    douyin: {
      status: null,
      signal: "SIGTERM",
      error: new Error("spawnSync ETIMEDOUT"),
      stdout: "",
      stderr: "",
    },
  });
  assert.equal(result.code, 1);
  assert.equal(result.summary.total, 1);
  assert.equal(result.summary.failed, 1);
  assert.equal(result.results[0].ok, false);
  assert.equal(result.results[0].exitCode, null);
  assert.equal(result.results[0].signal, "SIGTERM");
  assert.match(result.results[0].failure, /ETIMEDOUT/);
});

test("只有子进程成功退出且结果通过时才返回成功", () => {
  const result = run({
    x: { status: 0, signal: null, stdout: '{"platform":"x","ok":true}\n', stderr: "" },
    douyin: { status: 0, signal: null, stdout: '{"platform":"douyin","ok":true}\n', stderr: "" },
  });
  assert.equal(result.code, 0);
  assert.equal(result.summary.total, 2);
  assert.equal(result.summary.failed, 0);
  assert.deepEqual(result.results.map((one) => one.platform), ["x", "douyin"]);
});
