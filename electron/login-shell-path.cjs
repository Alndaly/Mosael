/**
 * 打包版要一份**用户终端里那样的** PATH。
 *
 * 从 Finder / Dock 启动的应用,PATH 是 launchd 给的最小集(`/usr/bin:/bin:/usr/sbin:/sbin`)——
 * Homebrew 的 `/opt/homebrew/bin`、nvm 的 node、uv 的 `~/.local/bin` 都不在里面。后端和它起的
 * 插件进程继承的就是这份,于是 Blender 插件找不到 `uvx`、Remotion 插件找不到 `node`,而同一台
 * 机器在终端里 `pnpm dev` 起来一切正常 —— 开发时永远撞不到。
 *
 * 做法:起一次用户的登录 shell 让它把环境吐出来,取其中的 PATH,和现有的合并去重。
 * - 读 `env` 的输出而不是 `echo $PATH`:fish 的 `$PATH` 是列表,只有导出到环境时才用冒号连。
 * - 用标记把输出包起来:rc 文件里打印东西的人很多,不能指望输出只有那一段。
 * - 有超时、失败就退回原样:拿不到更好的 PATH 不该让应用起不来。
 * - Windows 不需要:图形程序本来就继承完整的 PATH。
 */
const { execFileSync } = require("node:child_process");
const path = require("node:path");

const MARKER = "__MOSAEL_LOGIN_ENV__";

function mergePaths(...lists) {
  const seen = new Set();
  const out = [];
  for (const list of lists) {
    for (const entry of String(list || "").split(path.delimiter)) {
      if (entry && !seen.has(entry)) {
        seen.add(entry);
        out.push(entry);
      }
    }
  }
  return out.join(path.delimiter);
}

/** 从 `echo 标记; env; echo 标记` 的输出里取 PATH。取不到返回空串。 */
function pathFromEnvDump(output) {
  const start = output.indexOf(MARKER);
  const end = output.lastIndexOf(MARKER);
  if (start < 0 || end <= start) return "";
  const line = output.slice(start + MARKER.length, end).split(/\r?\n/).find((one) => one.startsWith("PATH="));
  return line ? line.slice("PATH=".length).trim() : "";
}

function loginShellPath({ platform = process.platform, env = process.env, run = execFileSync } = {}) {
  const current = env.PATH || "";
  if (platform === "win32") return current;
  const shell = env.SHELL || (platform === "darwin" ? "/bin/zsh" : "/bin/sh");
  try {
    const output = run(shell, ["-ilc", `echo ${MARKER}; env; echo ${MARKER}`], {
      encoding: "utf8",
      timeout: 5000,
      stdio: ["ignore", "pipe", "ignore"],
      // oh-my-zsh 之类在交互 shell 里会去检查更新、弹提示 —— 别让它在这儿等。
      env: { ...env, DISABLE_AUTO_UPDATE: "true", ZSH_DISABLE_COMPFIX: "true" },
    });
    const found = pathFromEnvDump(String(output));
    // 登录 shell 的在前:它就是用户在终端里看到的那一份;原来那几项补在后面,一项不丢。
    return found ? mergePaths(found, current) : current;
  } catch {
    return current;
  }
}

module.exports = { loginShellPath, mergePaths, pathFromEnvDump, MARKER };
