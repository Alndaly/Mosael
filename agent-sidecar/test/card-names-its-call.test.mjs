/**
 * 调工具时报上**这是哪一次调用**(pi 的 toolCallId),后端开卡时记在卡上。
 *
 * 对话界面靠它把确认卡摆回发起它的那次工具调用 —— 此前卡只知道属于哪次对话,五条「生成音频」的卡
 * 只能一张接一张堆在输入框上面(用户截图)。这个 id 只管摆位,不管授权:归属仍由令牌决定。
 *
 * 跑法:node agent-sidecar/test/card-names-its-call.test.mjs
 */
import assert from "node:assert/strict";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");

async function bundle(entry, outfile) {
  const esbuild = await import("esbuild");
  await esbuild.build({
    entryPoints: [entry],
    bundle: true,
    platform: "node",
    format: "esm",
    external: ["@earendil-works/pi-agent-core"],
    outfile,
  });
  return pathToFileURL(outfile).href;
}

const MANIFEST = [
  { name: "render_sequence", description: "导", parameters: { type: "object", properties: {} }, confirmation: true },
  { name: "list_assets", description: "列", parameters: { type: "object", properties: {} }, read_only: true },
];

const bodies = {};
const server = http.createServer((req, res) => {
  const json = (body) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  };
  if (req.url === "/api/agent/tools") return json(MANIFEST);
  if (req.url === "/api/confirmations/c1") return json({ id: "c1", status: "executed", result: { ok: true } });
  if (req.method === "POST" && req.url?.startsWith("/api/agent/tools/")) {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      const name = req.url.slice("/api/agent/tools/".length);
      bodies[name] = JSON.parse(raw);
      json(name === "render_sequence" ? { result: { confirmation_id: "c1", status: "pending" } } : { result: [] });
    });
    return;
  }
  res.writeHead(404);
  res.end("{}");
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;

try {
  const out = await bundle(path.join(root, "src", "tools.ts"), path.join(root, "dist", "tools.call-id-bundle.mjs"));
  const { buildAllTools } = await import(out);
  const tools = await buildAllTools(base, "t", "w1");

  await tools.find((one) => one.name === "render_sequence").execute("call-42", {});
  assert.equal(bodies.render_sequence?.tool_call_id, "call-42", "开卡的那次调用没把 toolCallId 报给后端");

  // 不开卡的工具也带上:后端只在开卡时用它,报不报不该由 sidecar 按工具分辨。
  await tools.find((one) => one.name === "list_assets").execute("call-43", {});
  assert.equal(bodies.list_assets?.tool_call_id, "call-43");
  console.log("card-names-its-call: ok");
} finally {
  server.close();
}
