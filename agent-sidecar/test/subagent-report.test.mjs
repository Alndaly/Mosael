// 子智能体的结论提取:content 是**块数组**,不是字符串。
//
// pi-ai 的 AssistantMessage.content 类型是 (TextContent|ThinkingContent|ToolCall)[] ——
// 按 `typeof content === "string"` 取正文永远取不到,表现是子智能体明明答了,却回
// 「没有产出结论」(真机两次派发全中)。这个测试直接吃打包产物里的行为:把 subagent.ts
// 单独打出来跑,免得测试和实现各自理解一遍消息形状。
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert";
// esbuild 走 JS API,不 spawn 子进程:Windows 上 `npx` 其实是 `npx.cmd`,
// spawnSync("npx") 直接 ENOENT —— v0.19.0 首跑就折在 win runner 这一步。
import { buildSync } from "esbuild";

const dir = mkdtempSync(join(tmpdir(), "subagent-test-"));
try {
  buildSync({
    entryPoints: [fileURLToPath(new URL("../src/subagent.ts", import.meta.url))],
    bundle: true,
    platform: "node",
    format: "esm",
    external: ["@earendil-works/*"],
    outfile: join(dir, "subagent.mjs"),
  });
  // assistantText 未导出 —— 通过 runSubagent 走完整路径成本高(要假 Agent),这里退一步:
  // 断言源码不再按字符串取(防退化),行为由下面的形状断言覆盖。
  const { readFileSync } = await import("node:fs");
  const bundled = readFileSync(join(dir, "subagent.mjs"), "utf8");
  assert.ok(bundled.includes("assistantText"), "结论提取的辅助没了?");
  assert.ok(!/record\.content === "string"/.test(bundled), "又退回按字符串取 content 了");

  // 形状断言:块数组抽正文。直接 eval 打包产物里的函数(它是模块内函数,拿不到就构造同款输入
  // 验证正则……不如直接在这里复刻调用:用 Function 从产物源码里取出 assistantText)。
  const match = bundled.match(/function assistantText\(message\) \{[\s\S]*?\n\}/);
  assert.ok(match, "在产物里找不到 assistantText 函数体");
  const assistantText = new Function(`${match[0]}; return assistantText;`)();
  assert.equal(
    assistantText({ role: "assistant", content: [
      { type: "thinking", thinking: "想一想" },
      { type: "text", text: "结论是 A" },
      { type: "toolCall", id: "t1" },
      { type: "text", text: "补充 B" },
    ] }),
    "结论是 A\n补充 B",
  );
  assert.equal(assistantText({ role: "assistant", content: [{ type: "toolCall", id: "t1" }] }), "");
  assert.equal(assistantText({ role: "assistant", content: "纯字符串也兼容" }), "纯字符串也兼容");
  console.log("subagent-report.test.mjs ok");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
