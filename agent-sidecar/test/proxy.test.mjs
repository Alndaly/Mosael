/**
 * 出站代理是否真的生效。
 *
 * 这条必须用真的代理服务器来测,因为失败模式是**静默的**:Node 的 fetch 默认不读
 * HTTP_PROXY,请求照样成功(直连),只是没走代理 —— 你要到被对方按地区拒绝时才发现,
 * 而那时看起来像是"代理没开"。所以判据是「代理服务器收到了这次请求」,不是「请求成功了」。
 *
 * 第二条同样要命:回环**必须**绕过代理。sidecar 的每次工具调用都回连本机后端,一旦被送进
 * 代理,整个智能体全废,表现却是"所有工具超时",几乎不会有人联想到代理。
 *
 * 跑法:node agent-sidecar/test/proxy.test.mjs
 */
import assert from "node:assert/strict";
import http from "node:http";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");

// 现打一份 ESM:installProxyFromEnv 要在装载时读环境,得能控制装载时机。
// undici 留作 external —— 它是 CJS,内部用 require 取 node 内建模块,打进 ESM 会在加载时炸
//("Dynamic require of node:assert is not supported")。真实产物是 CJS 没这问题,而那条路径
// 由 bundle.smoke.mjs 覆盖。
// 落在包内(dist 已被忽略):放到系统临时目录的话,ESM 解析 undici 会找不到 node_modules。
const out = path.join(root, "dist", "proxy.test-bundle.mjs");
execFileSync(
  path.join(root, "node_modules", ".bin", "esbuild"),
  [
    path.join(root, "src", "proxy.ts"),
    "--bundle",
    "--platform=node",
    "--format=esm",
    "--external:undici",
    `--outfile=${out}`,
  ],
  { cwd: root, stdio: "pipe" },
);

/** 假代理:普通 HTTP 代理收到的是带完整 URL 的请求行。记下来即可证明"走了代理"。 */
function startProxy() {
  const seen = [];
  const server = http.createServer((req, res) => {
    seen.push(req.url);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ via: "proxy" }));
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ seen, server, port: server.address().port }));
  });
}

/** 假"外部服务":直连才会打到它。 */
function startOrigin() {
  const seen = [];
  const server = http.createServer((req, res) => {
    seen.push(req.url);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ via: "direct" }));
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ seen, server, port: server.address().port }));
  });
}

const proxy = await startProxy();
const origin = await startOrigin();

// 1) 配了代理 → 外部请求走代理
{
  process.env.HTTP_PROXY = `http://127.0.0.1:${proxy.port}`;
  process.env.HTTPS_PROXY = process.env.HTTP_PROXY;
  // 回环绕过(后端会强制补这几项,这里照搬它的产物)
  process.env.NO_PROXY = "localhost,127.0.0.1,::1,0.0.0.0";

  const { installProxyFromEnv } = await import(`${out}?case=1`);
  installProxyFromEnv();

  // 用一个不存在的外部域名:直连必然 DNS 失败,走代理才会成功 —— 成败本身就是证据,
  // 再叠加代理端的记录,双保险。
  const res = await fetch("http://example.invalid/probe");
  const body = await res.json();
  assert.equal(body.via, "proxy", "外部请求没走代理");
  assert.ok(
    proxy.seen.some((url) => url.includes("example.invalid")),
    `代理没收到这次请求,实际收到:${JSON.stringify(proxy.seen)}`,
  );
}

// 2) NO_PROXY 里的回环 → 直连,不经代理
{
  const before = proxy.seen.length;
  const res = await fetch(`http://127.0.0.1:${origin.port}/api/agent/tools`);
  const body = await res.json();
  assert.equal(body.via, "direct", "回环请求被送进了代理 —— 智能体的工具调用会全部失效");
  assert.equal(proxy.seen.length, before, "代理不该看到回环请求");
  assert.ok(origin.seen.some((url) => url.includes("/api/agent/tools")));
}

// 3) 没配代理 → 什么都不装,保持直连
{
  for (const key of ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]) {
    delete process.env[key];
  }
  const { installProxyFromEnv } = await import(`${out}?case=3`);
  const before = proxy.seen.length;
  installProxyFromEnv();
  const res = await fetch(`http://127.0.0.1:${origin.port}/plain`);
  assert.equal((await res.json()).via, "direct");
  assert.equal(proxy.seen.length, before, "没配代理却还是走了代理");
}

proxy.server.close();
origin.server.close();
console.log("PASS  出站代理 3 组断言全过(走代理 / 回环绕过 / 未配置直连)");
