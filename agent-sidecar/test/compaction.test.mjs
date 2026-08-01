/**
 * 上下文压缩。
 *
 * 每条断言都对应一个"不这么做就会真的坏"的点:
 * 切在非 user 边界 → orphan tool_call,下一次请求直接被供应商拒;
 * 水位靠估算而不用供应商回报的数字 → 长对话里越估越偏;
 * 摘要失败让整轮失败 → 一次摘要抖动毁掉用户正在进行的工作。
 */
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";

// 源码是 TS。用 esbuild 的 **JS API** 现编译成 ESM 再 import ——
// 不走 node_modules/.bin 的可执行垫片:那玩意在 Windows 上是 .CMD,execFile 起不来(CI 红过)。
// 也不从 dist/sidecar.cjs 里正则抠函数:这个模块导出项多,抠出来的那份很容易和真正跑的不一致。
const here = path.dirname(fileURLToPath(import.meta.url));
const outfile = path.join(mkdtempSync(path.join(tmpdir(), "compaction-")), "compaction.mjs");
await build({
  entryPoints: [path.join(here, "..", "src", "compaction.ts")],
  outfile,
  bundle: true,
  format: "esm",
  platform: "node",
});
// 绝对路径要转成 file:// URL —— 裸路径在 Windows 上会被当成协议名(ERR_UNSUPPORTED_ESM_URL_SCHEME)。
const {
  COMPACT_RATIO,
  KEEP_RECENT,
  compact,
  contextTokens,
  estimateTokens,
  shouldCompact,
  splitPoint,
  summaryMessage,
} = await import(pathToFileURL(outfile).href);

const user = (text) => ({ role: "user", content: text });
const assistant = (text, usage) => ({ role: "assistant", content: text, ...(usage ? { usage } : {}) });

test("水位以供应商回报的 usage 为锚,只估算它之后新增的部分", () => {
  const messages = [
    user("很久以前的一大段话".repeat(500)),
    assistant("回复", { input: 4000, output: 200 }),
    user("刚问的"), // 锚之后,估算
  ];
  const total = contextTokens(messages);
  // 4200 是真实数字;整段估算会得到远大于它的值(第一条就上千 token)。
  assert.ok(total >= 4200 && total < 4300, `期望 4200 出头,实际 ${total}`);
});

test("一条 usage 都没有时整段估算", () => {
  const messages = [user("abcdefg"), user("hijklmn")];
  assert.equal(contextTokens(messages), estimateTokens(messages[0]) + estimateTokens(messages[1]));
});

test("工具参数与结果要计入 —— 它们往往是最占地方的那部分", () => {
  const withTool = { role: "assistant", content: [{ type: "tool_use", input: { path: "x".repeat(400) } }] };
  assert.ok(estimateTokens(withTool) > 100);
});

test("超过窗口的 80% 才触发", () => {
  const messages = [assistant("a", { input: 79, output: 0 })];
  assert.equal(shouldCompact(messages, 100), false);
  assert.equal(shouldCompact([assistant("a", { input: 81, output: 0 })], 100), true);
  assert.equal(COMPACT_RATIO, 0.8);
});

test("窗口未知(0)时不压缩 —— 宁可不动,也不按一个瞎猜的分母切", () => {
  assert.equal(shouldCompact([assistant("a", { input: 999999, output: 0 })], 0), false);
});

test("切点回退到 user 边界,不切断工具调用与结果的配对", () => {
  const messages = [
    user("u0"),
    assistant("a0"),
    user("u1"),
    ...Array.from({ length: KEEP_RECENT }, (_, i) => assistant(`tool-${i}`)),
  ];
  const cut = splitPoint(messages);
  assert.equal(messages[cut].role, "user", "切点必须落在 user 上");
});

test("短对话不切", () => {
  assert.equal(splitPoint([user("a"), assistant("b")]), 0);
});

test("压缩把早期换成摘要,并报告压掉了多少", async () => {
  const messages = [
    user("目标是做一个视频"),
    assistant("好的", { input: 90, output: 10 }),
    user("继续"),
    ...Array.from({ length: KEEP_RECENT }, (_, i) => assistant(`step-${i}`)),
  ];
  const result = await compact(messages, {
    contextWindow: 100,
    summarize: async () => "用户要做视频,已确认分辨率 1080p。",
  });
  assert.ok(result.info, "应当发生压缩");
  assert.equal(result.messages[0].role, "user");
  assert.match(result.messages[0].content, /交接说明/);
  assert.match(result.messages[0].content, /1080p/);
  assert.ok(result.info.droppedMessages > 0);
  assert.ok(result.info.tokensAfter < result.info.tokensBefore);
});

test("摘要失败退回截断,而不是让这一轮跟着失败", async () => {
  const messages = [
    user("u"),
    assistant("a", { input: 900, output: 0 }),
    user("u2"),
    ...Array.from({ length: KEEP_RECENT }, (_, i) => assistant(`s${i}`)),
  ];
  const result = await compact(messages, {
    contextWindow: 100,
    summarize: async () => {
      throw new Error("模型挂了");
    },
  });
  assert.ok(result.info, "仍然要报告压缩发生过 —— 静默丢弃比丢弃本身更糟");
  assert.equal(result.info.summary, "");
  assert.ok(result.messages.length < messages.length);
});

test("force 跳过水位判断 —— 对应界面上的「立即压缩」", async () => {
  const messages = [
    user("u"),
    assistant("a", { input: 1, output: 1 }),
    user("u2"),
    ...Array.from({ length: KEEP_RECENT }, (_, i) => assistant(`s${i}`)),
  ];
  assert.equal(shouldCompact(messages, 1_000_000), false);
  const result = await compact(messages, { contextWindow: 1_000_000, force: true, summarize: async () => "摘要" });
  assert.ok(result.info, "force 时即便远未到阈值也要压");
});

test("摘要挂成 user 而不是第二条 system", () => {
  // 多轮里 system 只应有一条,塞第二条会让部分供应商直接报错。
  assert.equal(summaryMessage("x").role, "user");
});
