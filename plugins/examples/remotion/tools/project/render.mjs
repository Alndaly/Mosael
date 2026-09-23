/**
 * 真正干活的那一段:打包 → 选画面 → 渲成 mp4。由 main.py 起,参数走 stdin(一份 JSON),
 * 结果在 stdout 最后一行(一份 JSON),进度写 stderr。
 *
 * 为什么不让 Python 直接调:Remotion 只有 Node 的接口,而插件协议是 stdin/stdout 的 JSON ——
 * 中间这一层就是翻译。
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

const request = JSON.parse(readFileSync(0, "utf8"));
const say = (line) => process.stderr.write(`${line}\n`);

try {
  const browser = request.browserExecutable ? { browserExecutable: request.browserExecutable } : {};
  const chromeMode = request.chromeMode || "headless-shell";
  const serveUrl = await bundle({
    entryPoint: path.join(request.projectDir, "src", "index.ts"),
    // 缓存按入口路径分:共享工程每次同一个入口,第二次起打包只要几秒。
    enableCaching: true,
    onProgress: (percent) => { if (percent % 25 === 0) say(`bundle ${percent}%`); },
  });
  const composition = await selectComposition({
    serveUrl, id: request.composition, inputProps: request.inputProps, chromeMode, logLevel: "error", ...browser,
  });
  let lastTenth = -1;
  await renderMedia({
    composition, serveUrl, codec: "h264", outputLocation: request.output, inputProps: request.inputProps,
    chromeMode, logLevel: "error", ...browser,
    ...(request.licenseKey ? { licenseKey: request.licenseKey } : {}),
    onProgress: ({ progress }) => {
      const tenth = Math.floor(progress * 10);
      if (tenth !== lastTenth) { lastTenth = tenth; say(`render ${tenth * 10}%`); }
    },
  });
  process.stdout.write(`${JSON.stringify({
    ok: true, output: request.output, width: composition.width, height: composition.height,
    fps: composition.fps, frames: composition.durationInFrames,
    seconds: Math.round((composition.durationInFrames / composition.fps) * 10) / 10,
  })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({ ok: false, error: String(error?.stack || error) })}\n`);
  process.exitCode = 1;
}
