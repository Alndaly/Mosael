/**
 * BackendCredentialStore 的判据。
 *
 * 它实现的是 pi 的 `CredentialStore.modify` 契约,而契约里最要紧的一条是**跨进程互斥**:
 * 订阅制的 refresh token 多为一次性,两个 sidecar 同时刷新时后手会让先手刚存好的凭据当场作废
 * ——用户看到「刚登录就被登出」。所以这里不测「能不能存下来」,测的是:
 *   1. 刷新前必须先取到租约(acquire),不能直接 PUT;
 *   2. 传给 fn 的是**后端那份**而不是帧里带下来的旧值(别人刚刷新过时,用旧的去换只会 invalid_grant);
 *   3. 刷新抛错要立刻 release,否则下一轮对话白等一个 TTL;
 *   4. commit 被拒(租约超时被顶替)不能让整轮对话失败——内存里这份本轮仍可用。
 *
 * 用一个假后端,因为要断言的是调用顺序,不是后端实现(那边有 Python 测试)。
 *
 * 跑法:node agent-sidecar/test/credentials.test.mjs
 */
import assert from "node:assert/strict";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");

/**
 * 用 esbuild 的 **JS API** 现打一份出来引入。
 *
 * 不能去 exec `node_modules/.bin/esbuild`:那在 Windows 上是 `.CMD` 垫片,execFileSync 不带
 * shell 根本起不来 —— 本地 macOS 全绿、Windows 打包 CI 直接红(真实事故)。JS API 三个平台一致。
 */
async function bundle(entry, outfile, external = []) {
  const esbuild = await import("esbuild");
  await esbuild.build({
    entryPoints: [entry],
    bundle: true,
    platform: "node",
    format: "esm",
    external,
    outfile,
  });
  // 返回 file:// URL 而不是裸路径:Windows 上 `import("D:\\...")` 会被 ESM loader 当成
  // 协议名 'd:' 拒掉(ERR_UNSUPPORTED_ESM_URL_SCHEME)。同样是本地 macOS 全绿、Windows CI 红。
  return pathToFileURL(outfile).href;
}

// 这个类引用了模块级常量(重试次数)和 log(),从 dist/sidecar.cjs 里正则抠出类体会漏掉它们。
// 打包产物本身能不能跑由 bundle.smoke.mjs 负责,这里测的是逻辑。
// 落在包内(dist 已被忽略):放到系统临时目录的话,ESM 解析依赖会找不到 node_modules。
const { BackendCredentialStore } = await import(
  await bundle(path.join(root, "src", "credentials.ts"), path.join(root, "dist", "credentials.test-bundle.mjs"))
);

/** 假后端:记录调用顺序,按脚本回应。 */
function startBackend(script) {
  const calls = [];
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      const step = req.url.split("/").pop();
      calls.push({ step, body: body ? JSON.parse(body) : null, auth: req.headers.authorization });
      const reply = script[step] ?? { status: 200, json: {} };
      res.writeHead(reply.status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(reply.json ?? {}));
    });
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () =>
      resolve({ calls, server, base: `http://127.0.0.1:${server.address().port}` }),
    );
  });
}

const OLD = { type: "oauth", access: "旧", refresh: "r0", expires: 1 };
const STORED = { type: "oauth", access: "后端那份", refresh: "r1", expires: 2 };
const NEW = { type: "oauth", access: "新", refresh: "r2", expires: 3 };

// 1) read 不走网络(帧里带下来的那份),modify 走 acquire → commit
{
  const { calls, server, base } = await startBackend({
    acquire: { status: 200, json: { lease: "L1", credential: STORED, version: 3 } },
    commit: { status: 200, json: { version: 4 } },
  });
  const store = new BackendCredentialStore(base, "tok", "prof-1", OLD);

  assert.deepEqual(await store.read(), OLD, "read 应当用帧里带下来的凭据,不该多一次网络往返");
  assert.equal(calls.length, 0, "read 不该发起请求");

  let seen;
  const out = await store.modify("prof-1", async (current) => {
    seen = current;
    return NEW;
  });

  assert.deepEqual(
    seen,
    STORED,
    "传给刷新函数的必须是后端那份 —— 别人刚刷新过时,用帧里的旧值去换只会 invalid_grant",
  );
  assert.deepEqual(out, NEW);
  assert.deepEqual(
    calls.map((c) => c.step),
    ["acquire", "commit"],
    "必须先加锁再写回;少了 acquire 就等于两个 sidecar 能同时刷新",
  );
  assert.equal(calls[1].body.lease, "L1", "commit 必须带上租约");
  assert.deepEqual(calls[1].body.credential, NEW);
  assert.equal(calls[0].auth, "Bearer tok");
  server.close();
}

// 2) 刷新抛错 → 立刻 release,不留着锁等 TTL
{
  const { calls, server, base } = await startBackend({
    acquire: { status: 200, json: { lease: "L2", credential: STORED, version: 1 } },
  });
  const store = new BackendCredentialStore(base, "tok", "prof-2", OLD);
  await assert.rejects(
    store.modify("prof-2", async () => {
      throw new Error("invalid_grant");
    }),
    /invalid_grant/,
    "刷新失败必须原样抛出,让上层知道要重新登录",
  );
  assert.deepEqual(
    calls.map((c) => c.step),
    ["acquire", "release"],
    "刷新失败没有放手 —— 下一轮对话要白等一个 TTL",
  );
  server.close();
}

// 3) fn 返回 undefined(pi 的「不改动」)→ 释放,不写
{
  const { calls, server, base } = await startBackend({
    acquire: { status: 200, json: { lease: "L3", credential: STORED, version: 1 } },
  });
  const store = new BackendCredentialStore(base, "tok", "prof-3", OLD);
  const out = await store.modify("prof-3", async () => undefined);
  assert.deepEqual(out, STORED, "不改动时应当返回后端那份");
  assert.deepEqual(calls.map((c) => c.step), ["acquire", "release"], "没有改动就不该写");
  server.close();
}

// 4) acquire 撞锁(409)后重试,别人放手后能拿到
{
  let attempt = 0;
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const step = req.url.split("/").pop();
      if (step === "acquire") {
        attempt += 1;
        if (attempt < 3) {
          res.writeHead(409, { "Content-Type": "application/json" });
          return res.end(JSON.stringify({ detail: "凭据正被另一次刷新占用" }));
        }
        res.writeHead(200, { "Content-Type": "application/json" });
        return res.end(JSON.stringify({ lease: "L4", credential: STORED, version: 1 }));
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ version: 2 }));
    });
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const store = new BackendCredentialStore(base, "tok", "prof-4", OLD);
  const out = await store.modify("prof-4", async () => NEW);
  assert.deepEqual(out, NEW, "撞锁应当重试 —— 对方几秒内就会结束");
  assert.equal(attempt, 3);
  server.close();
}

// 5) commit 被拒(租约被顶替)不该让整轮对话失败
{
  const { server, base } = await startBackend({
    acquire: { status: 200, json: { lease: "L5", credential: STORED, version: 1 } },
    commit: { status: 409, json: { detail: "租约已失效" } },
  });
  const store = new BackendCredentialStore(base, "tok", "prof-5", OLD);
  const out = await store.modify("prof-5", async () => NEW);
  assert.deepEqual(out, NEW, "写回被拒时内存里这份本轮仍然可用,不该把整轮对话拖失败");
  server.close();
}

// 6) sidecar 不负责登出
{
  const { server, base } = await startBackend({});
  const store = new BackendCredentialStore(base, "tok", "prof-6", OLD);
  await assert.rejects(store.delete("prof-6"), /登出/, "一次刷新失败不该清掉用户的订阅登录");
  server.close();
}

console.log("PASS  BackendCredentialStore 6 组断言全过");
