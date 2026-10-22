// 结构化事件日志(P7):一次登录 / 一个动作到底走到哪一步、什么时候停的。
//
// 现在的 `plog` 是自由文本,排查时得靠人从几百行里挑。视频号那几轮就是活例子:同一个「登不上」,
// 可能是「没进登录页」「进了但用户没操作」「判据抛错」「判据一直说不」「认出来了却又被踢」——
// 文本日志里它们长得几乎一样。
//
// 这里只写**一行一个 JSON**,固定字段:
//   ts(ISO) at(做完这一件事用了多久 ms) phase/scene 发生了什么 kind 是哪一类
//   account / session 指向谁 url 当时在哪(去掉查询串里的凭据) ok 结论 extra 别的
//
// 三条硬规矩:①不写 cookie 值 / 令牌 / 验证码;②URL 只留 origin+path(查询串整体抹掉);③文件有上限,
// 满了轮转一份 —— 它是排查用的,不该长成几十 MB。
const fs = require("node:fs");
const path = require("node:path");

/** 查询串里的这些都可能是凭据(视频号那串 URL 里就带着 code / state / ticket)。 */
const SENSITIVE =
  /^(code|state|ticket|token|auth_code|login_ticket|sessionid|access_token|refresh_token|cookie|set-cookie|authorization|password|secret|pass|key)$/i;

function safeUrl(raw) {
  const text = String(raw || "");
  if (!text) return "";
  try {
    const url = new URL(text);
    return `${url.origin}${url.pathname}`;
  } catch {
    return text.split("?")[0].slice(0, 200);
  }
}

/** 把任意对象里像凭据的键换成 `***`,并把值里出现的 URL 抹掉查询串。 */
function scrub(value, depth = 0) {
  if (depth > 3 || value === null || value === undefined) return value;
  if (typeof value === "string") return /^https?:\/\//i.test(value) ? safeUrl(value) : value.slice(0, 300);
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) return value.slice(0, 20).map((one) => scrub(one, depth + 1));
  if (typeof value === "object") {
    const out = {};
    for (const [key, val] of Object.entries(value).slice(0, 30)) {
      out[key] = SENSITIVE.test(key) ? "***" : scrub(val, depth + 1);
    }
    return out;
  }
  return String(value).slice(0, 100);
}

/**
 * 建一个写入器。`dir` 缺省就不写(测试/独立运行时不落盘);`maxBytes` 到了就轮转到 `.1`。
 * `now` / `fs` 可注入,测试里用替身。
 */
function createTrace(options = {}) {
  const dir = options.dir || "";
  const maxBytes = Number.isInteger(options.maxBytes) ? options.maxBytes : 2 * 1024 * 1024;
  const now = typeof options.now === "function" ? options.now : () => Date.now();
  const sink = options.fs || fs;
  const file = dir ? path.join(dir, "browser-trace.log") : "";

  function write(entry) {
    if (!file) return;
    const line = JSON.stringify(scrub(entry)) + "\n";
    try {
      sink.mkdirSync(dir, { recursive: true });
      try {
        if (sink.statSync(file).size > maxBytes) sink.renameSync(file, `${file}.1`);
      } catch {
        /* 还没有这个文件 */
      }
      sink.appendFileSync(file, line, { encoding: "utf8", mode: 0o600 });
    } catch {
      /* 日志写不出去不该影响业务 */
    }
  }

  return {
    /** 记一条:scene 是「在做什么」(login / action / navigation),其余字段自由。 */
    event(scene, fields = {}) {
      write({ ts: new Date(now()).toISOString(), scene: String(scene || "").slice(0, 40), ...fields });
    },
    /** 包住一段耗时操作:结束(或抛错)时记一条,自动带 ms 与结论。 */
    async span(scene, fields, run) {
      const started = now();
      try {
        const result = await run();
        write({
          ts: new Date(now()).toISOString(),
          scene: String(scene || "").slice(0, 40),
          ...fields,
          ok: true,
          at: now() - started,
        });
        return result;
      } catch (error) {
        write({
          ts: new Date(now()).toISOString(),
          scene: String(scene || "").slice(0, 40),
          ...fields,
          ok: false,
          at: now() - started,
          error: String((error && error.message) || error || "").slice(0, 200),
        });
        throw error;
      }
    },
    file,
  };
}

module.exports = { createTrace, safeUrl, scrub, SENSITIVE };
