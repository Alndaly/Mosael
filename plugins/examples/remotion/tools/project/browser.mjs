/**
 * 准备渲染用的浏览器:Remotion 自己的 Chrome Headless Shell(下到 node_modules/.remotion)。
 * 下不下来(国内常见 —— 它从 storage.googleapis.com 下)由 main.py 退到本机的 Chrome / Edge。
 */
import { ensureBrowser } from "@remotion/renderer";

try {
  let lastTenth = -1;
  const status = await ensureBrowser({
    logLevel: "error",
    onBrowserDownload: () => ({
      version: null,
      onProgress: ({ percent }) => {
        const tenth = Math.floor(percent * 10);
        if (tenth !== lastTenth) { lastTenth = tenth; process.stderr.write(`browser ${tenth * 10}%\n`); }
      },
    }),
  });
  process.stdout.write(`${JSON.stringify({ ok: true, status: status.type })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: String(error?.message || error) })}\n`);
  process.exitCode = 1;
}
