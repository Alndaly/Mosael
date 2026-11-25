/**
 * 按需工具:桌面控制 / 浏览器不进主工具表,由 tool_search 找到、run_tool 执行。
 * 这样才能把 60 多个定义从每轮上下文里拿出去,同时需要时又够得着。
 */
import assert from "node:assert/strict";
import http from "node:http";
import path from "node:path";

import { build } from "esbuild";

const root = path.join(import.meta.dirname, "..");
const outfile = path.join(root, "dist", "on-demand-tools.test.mjs");
await build({
  entryPoints: [path.join(root, "src", "tools.ts")],
  outfile,
  bundle: true,
  platform: "node",
  format: "esm",
  external: ["@earendil-works/pi-agent-core"],
});
const { buildAllTools } = await import(new URL(`file://${outfile}`).href);

const MANIFEST = [
  { name: "list_projects", description: "列项目", parameters: { type: "object", properties: {} }, read_only: true },
  { name: "browser_open", description: "打开浏览器页面", parameters: { type: "object", properties: { url: { type: "string" } } }, read_only: true },
  { name: "browser_read", description: "读浏览器页面", parameters: { type: "object", properties: {} }, read_only: true },
  { name: "computer_click", description: "点击桌面", parameters: { type: "object", properties: {} }, read_only: false },
];

const bodies = {};
const server = http.createServer((req, res) => {
  const json = (body) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  };
  if (req.url === "/api/agent/tools") return json(MANIFEST);
  if (req.method === "POST" && req.url?.startsWith("/api/agent/tools/")) {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      const name = req.url.slice("/api/agent/tools/".length);
      bodies[name] = JSON.parse(raw);
      json({ result: { name, ok: true } });
    });
    return;
  }
  res.writeHead(404);
  res.end("{}");
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;

try {
  const tools = await buildAllTools(base, "t", "w1");
  const names = new Set(tools.map((one) => one.name));

  assert(names.has("list_projects"), "普通工具仍直接可见");
  assert(names.has("tool_search") && names.has("run_tool") && names.has("run_read_tool"), "按需入口必须在");
  assert(!names.has("browser_open") && !names.has("computer_click"), "按需族不该进主工具表");

  const search = tools.find((one) => one.name === "tool_search");
  const found = JSON.parse((await search.execute("c1", { query: "browser" })).content[0].text);
  assert.deepEqual(found.tools.map((one) => one.name), ["browser_open", "browser_read"]);

  const cn = JSON.parse((await search.execute("c1b", { query: "截图" })).content[0].text);
  assert(cn.tools.some((one) => one.name === "computer_click"), "中文检索词也要能找到按需工具");

  const run = tools.find((one) => one.name === "run_tool");
  const result = await run.execute("c2", { name: "browser_open", arguments: { url: "https://example.com" } });
  assert.deepEqual(JSON.parse(result.content[0].text), { name: "browser_open", ok: true });
  assert.deepEqual(bodies.browser_open.arguments, { url: "https://example.com" });
  assert.equal(bodies.browser_open.tool_call_id, "c2");

  const read = tools.find((one) => one.name === "run_read_tool");
  const readResult = await read.execute("c3", { name: "browser_read", arguments: {} });
  assert.deepEqual(JSON.parse(readResult.content[0].text), { name: "browser_read", ok: true });
  await assert.rejects(
    () => read.execute("c4", { name: "computer_click", arguments: {} }),
    /not read-only/,
  );
  console.log("on-demand-tools: ok");
} finally {
  server.close();
}
