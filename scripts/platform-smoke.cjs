// 站点契约的**冒烟**:只用公开页面,判断「平台还认得出来吗」。
//
// 为什么需要它:发布链路的失败常常长得像成功 —— 上传传完了、按钮在但点不动,一句「did not confirm
// publish」;而真正的原因(平台改版、选择器/文案失配)在日志里和「点了但没生效」分不开。这里用一个
// **不登录**的浏览器把每家创作页/登录页打开,断言它还是那个站(textAny 或 urlAny 命中其一),再把结果
// 写成一行一个 JSON。平台改版当天就能看见,而不是等某次真发布失败。
//
// 跑法(需要 Electron;`--no-sandbox` 是**必须的**——容器/CI 里不加它,Chromium 会在加载途中崩掉,
// 本地 macOS 上不加也可能崩,所以别省):
//     ./node_modules/.bin/electron --no-sandbox scripts/platform-smoke.cjs            # 全部
//     ./node_modules/.bin/electron --no-sandbox scripts/platform-smoke.cjs x douyin   # 只跑这几家
// 退出码:有任何一家失败就是 1。
const fs = require("node:fs");
const path = require("node:path");

const CONTRACT = path.join(__dirname, "..", "contracts", "platform-contracts.json");
const LOAD_TIMEOUT_MS = 30_000;
const SETTLE_MS = 2_500;

function loadCases(only) {
  const contract = JSON.parse(fs.readFileSync(CONTRACT, "utf8"));
  const entries = Object.entries(contract.platforms || {});
  const wanted = only.length > 0 ? entries.filter(([id]) => only.includes(id)) : entries;
  return { contract, cases: wanted.map(([id, value]) => ({ id, ...value })) };
}

function judge(page, smoke) {
  const text = String(page.text || "");
  const url = String(page.url || "");
  const textHit = (smoke.textAny || []).filter((needle) => text.includes(needle));
  const urlHit = (smoke.urlAny || []).filter((needle) => url.includes(needle));
  return { ok: textHit.length > 0 || urlHit.length > 0, textHit, urlHit, textHead: text.slice(0, 160), url };
}

async function runOne(platformId) {
  const { app, BrowserWindow } = require("electron");
  //: 无头/容器里跑得动的那一套开关:几处探针(Computer Use、坐标换算)在相同环境下也是这么开的。
  app.disableHardwareAcceleration();
  app.commandLine.appendSwitch("no-sandbox");
  app.commandLine.appendSwitch("disable-gpu");
  app.commandLine.appendSwitch("disable-software-rasterizer");
  app.setPath("userData", path.join(app.getPath("temp"), `mosael-smoke-${process.pid}`));

  //: argv 里混着 `--no-sandbox` 与**脚本自己的路径**(Electron 的 argv[2] 就是它),都要剔掉,
  //: 否则「只跑某几家」会把它们当成平台名 → 一个都不跑(实测过一次:total 0)。
  const { contract, cases } = loadCases([platformId]);
  const results = [];

  await app.whenReady();
  for (const one of cases) {
    const win = new BrowserWindow({ width: 1280, height: 900, show: false });
    let failure = "";
    try {
      await Promise.race([
        win.loadURL(one.smoke.url),
        new Promise((_, reject) => setTimeout(() => reject(new Error("load timeout")), LOAD_TIMEOUT_MS)),
      ]);
      await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
      const page = await win.webContents.executeJavaScript(
        "({ url: location.href, text: document.body ? document.body.innerText : '' })",
      );
      const verdict = judge(page, one.smoke);
      results.push({ platform: one.id, ...verdict, ...(verdict.ok ? {} : { failure: `no marker: ${JSON.stringify(one.smoke)}` }) });
      if (!verdict.ok) failure = "markers missing";
    } catch (error) {
      //: **未登录时平台会跳自家登录页**,那次跳转会让最初那个 loadURL 以 ERR_ABORTED 失败 ——
      //: 这不是「站坏了」,恰恰是「站还在、只是要登录」。所以失败之后照样读一次页面再判。
      const aborted = /ERR_ABORTED|ERR_FAILED/.test(String((error && error.message) || ""));
      let verdict = { ok: false, textHit: [], urlHit: [], textHead: "", url: one.smoke.url };
      if (aborted) {
        try {
          await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
          const page = await win.webContents.executeJavaScript(
            "({ url: location.href, text: document.body ? document.body.innerText : '' })",
          );
          verdict = judge(page, one.smoke);
        } catch {
          /* 读不到就算了,下面记一条失败 */
        }
      }
      results.push({
        platform: one.id,
        ...verdict,
        ...(verdict.ok
          ? { redirected: true }
          : { failure: String((error && error.message) || error).slice(0, 200), url: one.smoke.url }),
      });
      if (!verdict.ok) failure = "load failed";
    } finally {
      win.destroy();
    }
    if (failure) console.error(`✗ ${one.id}: ${failure}`);
  }

  const failed = results.filter((one) => !one.ok);
  console.log(JSON.stringify({ contract: contract.contract, version: contract.version, at: new Date().toISOString(), total: results.length, failed: failed.length }));
  for (const one of results) console.log(JSON.stringify(one));
  app.exit(failed.length === 0 ? 0 : 1);
}

/**
 * 一家一个**子进程**:某个站会让渲染进程崩掉(实测小红书那条把整个 Electron 带 SIGTRAP),
 * 在同一进程里跑就会「一家有问题、其余几家一条结果都没有」。父进程只负责排队、收 JSON、汇总。
 *
 * 用 `spawnSync` 串行:一家最多半分钟,串行足够快;而异步 spawn 在这里要处理管道缓冲与退出竞态,
 * 多写的那些代码只会自己出问题(实测挂住过一次)。
 */
function runAll(platformIds, spawnSync = require("node:child_process").spawnSync) {
  const results = [];
  for (const id of platformIds) {
    const child = spawnSync(process.execPath, ["--no-sandbox", __filename, "--platform", id], {
      encoding: "utf8",
      timeout: LOAD_TIMEOUT_MS + SETTLE_MS + 20_000,
    });
    const out = `${child.stdout || ""}${child.stderr || ""}`;
    const line = out
      .split("\n")
      .find((one) => one.trim().startsWith("{") && one.includes("\"platform\""));
    let result;
    if (line) {
      try {
        result = JSON.parse(line);
      } catch {
        /* 落到下面记一条失败 */
      }
    }
    const detail = out.trim().slice(-200);
    const processFailure = child.error
      ? `child error: ${child.error.message}`
      : child.signal
        ? `child terminated by ${child.signal}`
        : child.status !== 0
          ? `child exited ${child.status}`
          : "";
    if (processFailure) {
      results.push({
        ...result,
        platform: id,
        ok: false,
        exitCode: child.status,
        signal: child.signal || undefined,
        failure: `${processFailure}${detail ? `: ${detail}` : ""}`,
      });
    } else if (result) {
      results.push(result);
    } else {
      results.push({ platform: id, ok: false, exitCode: child.status, failure: `child produced no result${detail ? `: ${detail}` : ""}` });
    }
  }
  const failed = results.filter((one) => !one.ok);
  console.log(JSON.stringify({ at: new Date().toISOString(), total: results.length, failed: failed.length }));
  for (const one of results) console.log(JSON.stringify(one));
  return failed.length === 0 ? 0 : 1;
}

const directPlatform = (() => {
  const index = process.argv.indexOf("--platform");
  return index >= 0 ? String(process.argv[index + 1] || "").trim() : "";
})();

if (require.main === module) {
  if (directPlatform) {
    runOne(directPlatform)
      .then((code) => process.exit(code))
      .catch((error) => {
        console.error("smoke crashed:", error);
        process.exit(1);
      });
  } else {
    const wanted = process.argv
      .slice(1)
      .filter((arg) => !arg.startsWith("-"))
      .filter((arg) => !/\.c?js$/.test(arg));
    const { cases } = loadCases(wanted);
    if (cases.length === 0) {
      console.error("没有要跑的平台(检查平台名拼写;空参数 = 全部)。");
      process.exit(2);
    }
    process.exit(runAll(cases.map((one) => one.id)));
  }
}

module.exports = { runAll };
