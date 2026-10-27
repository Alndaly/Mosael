import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { createServer } from "node:http";
import { once } from "node:events";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SCRIPT = path.join(ROOT, "scripts", "publish-r2.mjs");

async function withDist(run) {
  const dist = mkdtempSync(path.join(tmpdir(), "mosael-r2-publish-"));
  try {
    writeFileSync(path.join(dist, "latest-mac.yml"), "version: 2.2.4\n");
    writeFileSync(path.join(dist, "Mosael-2.2.4-arm64.dmg"), "dmg");
    return await run(dist);
  } finally {
    rmSync(dist, { recursive: true, force: true });
  }
}

test("R2 发布计划先完成整个不可变版本目录,再更新 latest", async () => {
  await withDist((dist) => {
    const output = execFileSync(process.execPath, [SCRIPT, "--dist", dist, "--tag", "v2.2.4", "--dry-run"], {
      cwd: ROOT,
      encoding: "utf8",
    });
    const keys = output.trim().split("\n").map((line) => JSON.parse(line).key);
    assert.equal(keys.length, 6);
    assert.ok(keys.slice(0, 3).every((key) => key.startsWith("mosael/v2.2.4/")));
    assert.ok(keys.slice(3).every((key) => key.startsWith("mosael/latest/")));
    const names = ["latest-mac.yml", "Mosael-2.2.4-arm64.dmg", "index.html"];
    assert.deepEqual(keys.toSorted(), [
      ...names.map((name) => `mosael/v2.2.4/${name}`),
      ...names.map((name) => `mosael/latest/${name}`),
    ].toSorted());
  });
});

test("不可变版本上传失败时,不会更新任何 latest 对象", async () => {
  await withDist(async (dist) => {
    const requests = [];
    const objects = new Map();
    const server = createServer((req, res) => {
      const pathname = new URL(req.url || "/", "http://r2.test").pathname;
      requests.push(`${req.method} ${pathname}`);
      const chunks = [];
      req.on("data", (chunk) => chunks.push(chunk));
      req.on("end", () => {
        if (req.method === "PUT" && pathname.endsWith("/v2.2.4/latest-mac.yml")) {
          res.writeHead(400, { "Content-Type": "application/xml" });
          res.end("<Error><Code>InvalidRequest</Code><Message>injected failure</Message></Error>");
          return;
        }
        if (req.method === "PUT") {
          let body = Buffer.concat(chunks);
          if (String(req.headers["content-encoding"] || "").includes("aws-chunked")) {
            const decoded = [];
            let offset = 0;
            while (offset < body.length) {
              const end = body.indexOf("\r\n", offset);
              const size = Number.parseInt(body.subarray(offset, end).toString(), 16);
              if (size === 0) break;
              decoded.push(body.subarray(end + 2, end + 2 + size));
              offset = end + 2 + size + 2;
            }
            body = Buffer.concat(decoded);
          }
          objects.set(pathname, body);
          res.writeHead(200, { "Content-Length": 0 });
          res.end();
          return;
        }
        const body = objects.get(pathname);
        if (!body) {
          res.writeHead(404, { "Content-Length": 0 });
          res.end();
          return;
        }
        res.writeHead(200, { "Content-Length": body.length });
        res.end(req.method === "HEAD" ? undefined : body);
      });
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const { port } = server.address();
    const child = spawn(process.execPath, [SCRIPT, "--dist", dist, "--tag", "v2.2.4"], {
      cwd: ROOT,
      env: {
        ...process.env,
        R2_ENDPOINT: `http://127.0.0.1:${port}`,
        R2_BUCKET: "releases",
        R2_ACCESS_KEY_ID: "test",
        R2_SECRET_ACCESS_KEY: "test",
      },
      stdio: ["ignore", "ignore", "pipe"],
    });
    let stderr = "";
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    const [code] = await once(child, "close");
    await new Promise((resolve) => server.close(resolve));
    assert.notEqual(code, 0, stderr);
    assert.equal(requests.some((line) => line.includes("/latest/")), false, requests.join("\n"));
  });
});
