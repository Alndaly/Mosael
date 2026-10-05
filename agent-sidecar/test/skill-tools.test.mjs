/**
 * 技能的两个工具(ADR 0040):use_skill / read_skill_file 从后端的工具清单来,**只读** —— 主智能体有,子智能体也有。
 *
 * sidecar 不认识「技能」这件事:它照 manifest 生成工具,只读与否看 `read_only`(名单在后端,见 mcp_server 的
 * `@tool(effect="reads")`)。这里钉住三件事:两个工具注册上了、带中文标签;子智能体的只读筛选拿得到它们、拿不到会改东西的;
 * 调用时补上这一轮的工作区,结果原样交给模型。
 *
 * 跑法:node agent-sidecar/test/skill-tools.test.mjs
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
    external: ["@earendil-works/pi-agent-core", "@earendil-works/pi-ai"],
    outfile,
  });
  return pathToFileURL(outfile).href;
}

const schema = (properties) => ({ type: "object", properties });
const MANIFEST = [
  { name: "use_skill", description: "Read-only: load a skill", parameters: schema({ name: { type: "string" }, workspace_id: { type: "string" } }), read_only: true },
  {
    name: "read_skill_file",
    description: "Read-only: read one file bundled with a skill",
    parameters: schema({ name: { type: "string" }, path: { type: "string" }, offset: { type: "integer" }, workspace_id: { type: "string" } }),
    read_only: true,
  },
  { name: "edit_timeline", description: "改时间线", parameters: schema({ sequence_id: { type: "string" } }), confirmation: true },
  { name: "remember", description: "记一条", parameters: schema({ content: { type: "string" } }) },
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
      json({ result: { name: "short-video-ads", title: "做带货短视频", instructions: "1. 先看商品图", files: [] } });
    });
    return;
  }
  res.writeHead(404);
  res.end("{}");
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;

try {
  const toolsUrl = await bundle(path.join(root, "src", "tools.ts"), path.join(root, "dist", "tools.skill-bundle.mjs"));
  const subagentUrl = await bundle(path.join(root, "src", "subagent.ts"), path.join(root, "dist", "subagent.skill-bundle.mjs"));
  const { buildAllTools } = await import(toolsUrl);
  const { readOnlyTools } = await import(subagentUrl);
  const tools = await buildAllTools(base, "t", "ws-1");

  const useSkill = tools.find((one) => one.name === "use_skill");
  const readFile = tools.find((one) => one.name === "read_skill_file");
  assert.ok(useSkill && readFile, "两个技能工具都要从清单里生成出来");
  assert.equal(useSkill.label, "使用技能");
  assert.equal(readFile.label, "读技能文件");
  assert.equal(useSkill.readOnly, true);
  assert.equal(useSkill.confirmation, false, "读一份说明不该开确认卡");

  const forSubagent = readOnlyTools(tools).map((one) => one.name).sort();
  assert.deepEqual(forSubagent, ["read_skill_file", "use_skill"], "子智能体只拿只读的:两个技能工具在,会改东西的不在");

  const result = await useSkill.execute("call-1", { name: "short-video-ads" });
  assert.equal(bodies.use_skill.arguments.workspace_id, "ws-1", "这一轮的工作区要补上");
  assert.equal(bodies.use_skill.arguments.name, "short-video-ads");
  assert.equal(result.details.data.instructions, "1. 先看商品图", "回包原样交给模型");
  console.log("skill-tools: ok");
} finally {
  server.close();
}
