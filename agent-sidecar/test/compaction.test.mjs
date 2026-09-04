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
  fitTurnContext,
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

test("轮内大工具结果会被压进预算，给模型回答保留空间", () => {
  const huge = JSON.stringify(Array.from({ length: 300 }, (_, index) => ({ index, detail: "配置说明".repeat(80) })));
  const messages = [
    user("请修改工作流"),
    assistant("我先检查", { input: 17_000, output: 20 }),
    { role: "toolResult", toolName: "list_workflow_node_types", content: [{ type: "text", text: huge }] },
  ];
  const fitted = fitTurnContext(messages, 23_000);
  assert.ok(contextTokens(fitted) <= 23_000, `轮内上下文应压到预算内，实际 ${contextTokens(fitted)}`);
  assert.match(JSON.stringify(fitted), /内容过长已截断/);
  assert.equal(JSON.stringify(messages).includes("内容过长已截断"), false, "只能裁发送副本，完整历史仍要保存");
});

test("预算充足时不改写工具结果", () => {
  const messages = [user("x"), { role: "toolResult", content: [{ type: "text", text: "short" }] }];
  assert.strictEqual(fitTurnContext(messages, 10_000), messages);
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

test("单轮工具结果已经超窗时也能压缩，而不是因消息不足八条永远卡死", async () => {
  const messages = [
    user("检查工作流"),
    assistant("开始检查", { input: 17_000, output: 20 }),
    { role: "toolResult", content: [{ type: "text", text: "完整配置".repeat(12_000) }] },
    assistant("我", { input: 31_999, output: 1 }),
  ];
  const result = await compact(messages, { contextWindow: 32_000, summarize: async () => "已检查工作流，待继续修改。" });
  assert.ok(result.info, "超窗的单轮历史必须能够整理");
  assert.equal(result.messages.length, 1);
  assert.match(String(result.messages[0].content), /待继续修改/);
});

test("压缩把早期换成摘要,并报告压掉了多少", async () => {
  // 早期部分必须够长:摘要本身也占地方,压一段本来就很短的历史是会变大的
  // (那种情况由 compact 自己判定为"没压",见下一条用例)。
  const messages = [
    user("目标是做一个视频。" + "详细需求".repeat(300)),
    assistant("好的" + "方案细节".repeat(300), { input: 90, output: 10 }),
    user("继续" + "补充说明".repeat(300)),
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
  // 早期部分要够长才压得出东西 —— force 绕过的是**水位阈值**,不是"压了反而更大"那条。
  const messages = [
    user("u".repeat(4000)),
    assistant("a".repeat(4000), { input: 1, output: 1 }),
    user("u2".repeat(2000)),
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

test("腾出的 token 不能用锚定值算 —— 那个数不会因为丢掉早期消息而变小", async () => {
  // 回归:tokensBefore/After 曾用 contextTokens 计算,而它锚定在最近一条 assistant 的
  // usage 上。那条消息压缩后还在(它属于保留的最近几条),于是前后完全相等,
  // 界面上永远显示「腾出约 0 token」。
  const messages = [
    user("很长很长的早期提问".repeat(200)),
    assistant("很长很长的早期回答".repeat(200)),
    user("中间的提问".repeat(200)),
    assistant("带 usage 的回答", { input: 12_000, output: 800 }),
    ...Array.from({ length: KEEP_RECENT }, (_, i) => user(`最近 ${i}`)),
  ];
  const result = await compact(messages, { contextWindow: 1_000_000, force: true, summarize: async () => "短摘要" });
  assert.ok(result.info, "force 应当压缩");
  assert.ok(
    result.info.tokensBefore - result.info.tokensAfter > 0,
    `应当报出正的节省量,实际 before=${result.info.tokensBefore} after=${result.info.tokensAfter}`,
  );
});

test("压完反而更大就不算压缩 —— 短对话上手动点「立即整理」会撞到", async () => {
  const messages = [
    user("目标是做一个视频"),
    assistant("好的", { input: 90, output: 10 }),
    user("继续"),
    ...Array.from({ length: KEEP_RECENT }, (_, i) => assistant(`step-${i}`)),
  ];
  const result = await compact(messages, {
    contextWindow: 1_000_000,
    force: true,
    summarize: async () => "这段摘要比被它换掉的三条短消息还长得多,压了等于白压。".repeat(3),
  });
  assert.equal(result.info, null, "变大就该报「没压」");
  assert.deepEqual(result.messages, messages, "原文必须原样保留");
});
