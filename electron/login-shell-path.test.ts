import { createRequire } from "node:module";
import { describe, expect, it, vi } from "vitest";

const { loginShellPath, pathFromEnvDump, MARKER } = createRequire(import.meta.url)("./login-shell-path.cjs");

const LAUNCHD = "/usr/bin:/bin:/usr/sbin:/sbin";

describe("打包版的 PATH 取自登录 shell", () => {
  it("rc 文件打印了东西也取得准,且登录 shell 的在前、原有的一项不丢", () => {
    const run = vi.fn(() => `Welcome back!\n${MARKER}\nHOME=/Users/u\nPATH=/opt/homebrew/bin:/usr/bin:/Users/u/.local/bin\nSHELL=/bin/zsh\n${MARKER}\nbye\n`);
    const out = loginShellPath({ platform: "darwin", env: { PATH: LAUNCHD, SHELL: "/bin/zsh" }, run });
    expect(out).toBe("/opt/homebrew/bin:/usr/bin:/Users/u/.local/bin:/bin:/usr/sbin:/sbin");
    // 起的是用户自己的 shell,登录 + 交互:rc 文件里那些 export 只有这样才会跑。
    expect(run.mock.calls[0][0]).toBe("/bin/zsh");
    expect(run.mock.calls[0][1][0]).toBe("-ilc");
  });

  it("fish 的列表形式由 env 导出成冒号连接,照样取得到", () => {
    // fish 里 `echo $PATH` 是空格分隔 —— 所以读的是 env 的输出,不是 echo。
    expect(pathFromEnvDump(`${MARKER}\nPATH=/opt/homebrew/bin:/usr/bin\n${MARKER}`)).toBe("/opt/homebrew/bin:/usr/bin");
  });

  it("shell 起不来或超时,退回原样 —— 拿不到更好的 PATH 不该让应用起不来", () => {
    const run = vi.fn(() => { throw new Error("ETIMEDOUT"); });
    expect(loginShellPath({ platform: "darwin", env: { PATH: LAUNCHD }, run })).toBe(LAUNCHD);
  });

  it("输出里没有标记(被 rc 吞了)也退回原样", () => {
    const run = vi.fn(() => "PATH=/evil/bin\n");
    expect(loginShellPath({ platform: "linux", env: { PATH: LAUNCHD, SHELL: "/bin/bash" }, run })).toBe(LAUNCHD);
  });

  it("Windows 不起 shell:图形程序本来就继承完整的 PATH", () => {
    const run = vi.fn();
    expect(loginShellPath({ platform: "win32", env: { PATH: "C:\\Windows" }, run })).toBe("C:\\Windows");
    expect(run).not.toHaveBeenCalled();
  });
});
