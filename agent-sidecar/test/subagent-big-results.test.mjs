/**
 * 子智能体的请求也过主智能体那道闸(guardRunawayTurn):超大的工具结果按窗口裁(智能体那一路 AGENT-12)。
 *
 * 现场:维护者库里一次子智能体的 list_jobs 回了 893 KB。子智能体此前没有这道闸 —— 它在最多 24 步的循环里每一步都把那 893 KB
 * 整段重发:窗口小的模型直接 400,1M 窗口的模型照单全收、照单付钱。
 *
 * 这里:模型窗口 32K;主智能体派一个子智能体(wait=true),子智能体调一个只读工具,工具回 30 万字;子智能体下一次请求里
 * 那段结果要被裁到窗口装得下的大小。
 *
 * 跑法:node agent-sidecar/test/subagent-big-results.test.mjs
 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "pi.subagent-big.mjs");
await build({
  entryPoints: [path.join(import.meta.dirname, "..", "src", "pi.ts")],
  outfile,
  format: "esm",
  bundle: true,
  platform: "node",
  packages: "external",
  ignoreAnnotations: true,
});
const { runPiTurn } = await import(pathToFileURL(outfile).href);

const BIG = "任务记录。".repeat(60_000); // 30 万字

test("子智能体拿到一个 30 万字的工具结果:它下一次请求里那段被裁到窗口装得下", async () => {
  const requests = [];
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      const parsed = JSON.parse(body || "{}");
      requests.push({ size: body.length, system: String(parsed.messages?.[0]?.content ?? ""), messages: parsed.messages ?? [] });
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      const chunk = (delta, finish = null) =>
        res.write(`data: ${JSON.stringify({ id: "c", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta, finish_reason: finish }] })}\n\n`);
      const isSubagent = String(parsed.messages?.[0]?.content ?? "").includes("子智能体");
      const sawTool = (parsed.messages ?? []).some((m) => m.role === "tool");
      if (!isSubagent && !sawTool) {
        chunk({ role: "assistant", tool_calls: [{ index: 0, id: "d1", type: "function", function: { name: "run_subagent", arguments: JSON.stringify({ task: "看一遍任务", wait: true }) } }] });
        chunk({}, "tool_calls");
      } else if (isSubagent && !sawTool) {
        chunk({ role: "assistant", tool_calls: [{ index: 0, id: "s1", type: "function", function: { name: "list_jobs", arguments: "{}" } }] });
        chunk({}, "tool_calls");
      } else {
        chunk({ role: "assistant", content: isSubagent ? "结论:都跑完了。" : "子智能体说都跑完了。" });
        chunk({}, "stop");
      }
      res.end("data: [DONE]\n\n");
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  const listJobs = {
    name: "list_jobs",
    label: "list_jobs",
    description: "列任务",
    parameters: { type: "object", properties: {} },
    readOnly: true,
    execute: async () => ({ content: [{ type: "text", text: BIG }], details: {} }),
  };
  try {
    const result = await runPiTurn(
      {
        systemPrompt: "s",
        prompt: "任务都跑完了吗",
        provider: { baseUrl: `http://127.0.0.1:${port}/v1`, apiKey: "k", vendor: "openai", contextWindow: 32_000, maxOutputTokens: 4096 },
        model: "m",
        tools: [listJobs],
        apiBase: "http://127.0.0.1:1",
        token: "t",
        thinkingLevel: "off",
      },
      { onDelta: () => {}, onThinking: () => {}, onThinkingEnd: () => {}, onToolStart: () => {}, onToolEnd: () => {} },
    );
    assert.equal(result.errorMessage, undefined, result.errorMessage);
    const subagentFollowUp = requests.find((one) => one.system.includes("子智能体") && one.messages.some((m) => m.role === "tool"));
    assert.ok(subagentFollowUp, "子智能体没有带着工具结果再发一次请求");
    const toolText = String(subagentFollowUp.messages.find((m) => m.role === "tool").content);
    assert.ok(toolText.length < BIG.length / 2, `子智能体把 ${toolText.length} 字的工具结果整段重发了(窗口 32K)`);
    assert.match(toolText, /截断/, "裁过的地方要写明");
  } finally {
    server.closeAllConnections();
    server.close();
  }
});
