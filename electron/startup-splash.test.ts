/**
 * 「正在启动」小窗(startup-splash.cjs):后端迁移 / 冷启动要好几分钟时,让人看见它在干什么,而不是 30 秒后弹「启动失败」。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

import { afterEach, describe, expect, it } from "vitest";

const { lastLogLine, splashHtml } = createRequire(import.meta.url)("./startup-splash.cjs") as {
  lastLogLine: (file: string, maxChars?: number) => string;
  splashHtml: (strings: { title: string; body: string; quit: string; lang: string }) => string;
};

const dirs: string[] = [];
function logFile(text: string): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-splash-"));
  dirs.push(dir);
  const file = path.join(dir, "backend.log");
  fs.writeFileSync(file, text);
  return file;
}
afterEach(() => {
  for (const dir of dirs.splice(0)) fs.rmSync(dir, { recursive: true, force: true });
});

describe("后端日志的最后一句", () => {
  it("取最后一条带时间和级别的日志,只留冒号后面那句话", () => {
    const file = logFile(
      [
        "2026-10-08 11:08:42 INFO    app.main: Mosael backend starting (host=127.0.0.1 port=8800)",
        "2026-10-08 11:08:45 INFO    app.domain.plugins.bundled: 装上随应用发的插件 dev.mosael.comfyui",
        "2026-10-08 11:08:51 INFO    app.db.migrations: 重建 agent_sessions 表(第 3 / 7 步)",
        "INFO:     127.0.0.1:57022 - \"GET /api/health HTTP/1.1\" 200 OK",
        "Traceback (most recent call last):",
        '  File "<string>", line 1, in <module>',
        "",
      ].join("\n"),
    );
    expect(lastLogLine(file)).toBe("重建 agent_sessions 表(第 3 / 7 步)");
  });

  it("太长的截短;没有日志文件、文件里没有像样的行都回空串", () => {
    expect(lastLogLine(logFile(`2026-10-08 11:08:51 WARNING app.x: ${"很长".repeat(200)}\n`), 20)).toHaveLength(20);
    expect(lastLogLine(path.join(os.tmpdir(), "no-such-mosael-log.log"))).toBe("");
    expect(lastLogLine(logFile("just noise\n"))).toBe("");
  });
});

describe("小窗的页面", () => {
  it("文案只当文字放进去:带标签的字符串不会变成 HTML,也关不掉 script", () => {
    const html = splashHtml({ title: "<img src=x onerror=alert(1)>", body: "</script><b>x</b>", quit: "退出", lang: "zh" });
    expect(html).not.toContain("<img src=x");
    expect(html).not.toContain("</script><b>");
    expect(html).toContain("textContent = strings.title");
    expect(html).toMatch(/Content-Security-Policy" content="default-src 'none'/);
  });

  it("「退出」就是关掉小窗(主进程把关窗当作不等了、退出)", () => {
    expect(splashHtml({ title: "t", body: "b", quit: "q", lang: "en" })).toContain('addEventListener("click", () => window.close())');
  });
});
