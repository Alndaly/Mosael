import React from "react";

import { useI18n } from "@/app/preferences";

type ScopeMode = "histogram" | "waveform";

// 采样分辨率:够画示波器又不拖累主线程。
const SAMPLE_W = 160;
const SAMPLE_H = 90;
const FRAME_MS = 1000 / 12; // ~12fps 采样

/** 示波器:从监视器 <video> 当前帧实时算直方图 / 波形。
 *  采样时套上与预览相同的 CSS filter(ctx.filter),所以示波器反映调色后的结果。
 *  跨域帧会污染 canvas → getImageData 抛错时优雅降级为提示。 */
export function Scopes({
  videoRef,
  filter,
}: {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  filter: string;
}) {
  const t = useI18n();
  const [mode, setMode] = React.useState<ScopeMode>("histogram");
  const [blocked, setBlocked] = React.useState(false);
  const displayRef = React.useRef<HTMLCanvasElement | null>(null);
  const sampleRef = React.useRef<HTMLCanvasElement | null>(null);
  // 用 ref 保存 filter/mode,避免 rAF 闭包吃到旧值又频繁重启循环。
  const filterRef = React.useRef(filter);
  const modeRef = React.useRef(mode);
  filterRef.current = filter;
  modeRef.current = mode;

  React.useEffect(() => {
    let raf = 0;
    let last = 0;
    if (!sampleRef.current) sampleRef.current = document.createElement("canvas");
    const sample = sampleRef.current;
    sample.width = SAMPLE_W;
    sample.height = SAMPLE_H;

    // 专用采样视频:主播放视频没有 crossOrigin(改了会命中"已缓存的非 CORS 响应"而加载失败)。
    // 这里用独立元素 + cache-buster 拿一份干净的 CORS 帧,canvas 不会被污染。
    const probe = document.createElement("video");
    probe.crossOrigin = "anonymous";
    probe.muted = true;
    probe.playsInline = true;
    probe.preload = "auto";
    let probeBase = ""; // 主视频 src(未加 buster),用于判断是否换源

    const syncSource = (mainSrc: string) => {
      if (mainSrc === probeBase) return;
      probeBase = mainSrc;
      probe.src = mainSrc ? mainSrc + (mainSrc.includes("?") ? "&" : "?") + "scope=1" : "";
    };

    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      if (now - last < FRAME_MS) return;
      last = now;
      const main = videoRef.current;
      const display = displayRef.current;
      if (!main || !display) return;
      syncSource(main.currentSrc || "");
      // 跟随主视频:播放时也让采样视频播,暂停/漂移时对齐 currentTime。
      // 只在真漂移时 seek —— 每帧重复 seek 会把 readyState 打回 1,画面永远画不出来。
      if (!main.paused && probe.paused) void probe.play().catch(() => {});
      if (main.paused && !probe.paused) probe.pause();
      const drift = Math.abs(probe.currentTime - main.currentTime);
      if (drift > (main.paused ? 0.05 : 0.35)) {
        try {
          probe.currentTime = main.currentTime;
        } catch {
          /* not seekable yet */
        }
      }
      if (probe.readyState < 2 || !probe.videoWidth) return;
      const sctx = sample.getContext("2d", { willReadFrequently: true });
      const dctx = display.getContext("2d");
      if (!sctx || !dctx) return;
      sctx.clearRect(0, 0, SAMPLE_W, SAMPLE_H);
      sctx.filter = filterRef.current || "none";
      try {
        sctx.drawImage(probe, 0, 0, SAMPLE_W, SAMPLE_H);
      } catch {
        return;
      }
      let pixels: Uint8ClampedArray;
      try {
        pixels = sctx.getImageData(0, 0, SAMPLE_W, SAMPLE_H).data;
      } catch {
        setBlocked(true); // canvas tainted — cross-origin frame without CORS
        cancelAnimationFrame(raf);
        return;
      }
      if (modeRef.current === "histogram") drawHistogram(dctx, display, pixels);
      else drawWaveform(dctx, display, pixels);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      probe.pause();
      probe.removeAttribute("src");
      probe.load();
    };
  }, [videoRef]);

  return (
    <div className="scopes">
      <div className="scopes-head">
        <div className="seg scopes-seg" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "histogram"}
            className={mode === "histogram" ? "seg-btn active" : "seg-btn"}
            onClick={() => setMode("histogram")}
          >
            {t("scopeHistogram")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "waveform"}
            className={mode === "waveform" ? "seg-btn active" : "seg-btn"}
            onClick={() => setMode("waveform")}
          >
            {t("scopeWaveform")}
          </button>
        </div>
      </div>
      <div className="scopes-canvas-wrap">
        <canvas ref={displayRef} width={256} height={128} className="scopes-canvas" />
        {blocked && <p className="scopes-blocked">{t("scopeUnavailable")}</p>}
      </div>
    </div>
  );
}

/** R/G/B 直方图,三通道叠加(additive)。 */
function drawHistogram(ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, px: Uint8ClampedArray): void {
  const W = canvas.width;
  const H = canvas.height;
  const r = new Float32Array(256);
  const g = new Float32Array(256);
  const b = new Float32Array(256);
  for (let i = 0; i < px.length; i += 4) {
    r[px[i]]++;
    g[px[i + 1]]++;
    b[px[i + 2]]++;
  }
  let peak = 1;
  for (let i = 0; i < 256; i++) peak = Math.max(peak, r[i], g[i], b[i]);
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#0b0b0d";
  ctx.fillRect(0, 0, W, H);
  ctx.globalCompositeOperation = "lighter";
  const channels: [Float32Array, string][] = [
    [r, "rgba(229,72,77,0.9)"],
    [g, "rgba(48,164,108,0.9)"],
    [b, "rgba(62,99,221,0.9)"],
  ];
  for (const [data, color] of channels) {
    ctx.beginPath();
    ctx.moveTo(0, H);
    for (let i = 0; i < 256; i++) {
      const x = (i / 255) * W;
      const y = H - (data[i] / peak) * H;
      ctx.lineTo(x, y);
    }
    ctx.lineTo(W, H);
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
  }
  ctx.globalCompositeOperation = "source-over";
}

/** 亮度波形:每列按行叠加密度,经典 waveform monitor。 */
function drawWaveform(ctx: CanvasRenderingContext2D, canvas: HTMLCanvasElement, px: Uint8ClampedArray): void {
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#0b0b0d";
  ctx.fillRect(0, 0, W, H);
  const img = ctx.getImageData(0, 0, W, H);
  const out = img.data;
  for (let sy = 0; sy < SAMPLE_H; sy++) {
    for (let sx = 0; sx < SAMPLE_W; sx++) {
      const p = (sy * SAMPLE_W + sx) * 4;
      const luma = (0.2126 * px[p] + 0.7152 * px[p + 1] + 0.0722 * px[p + 2]) / 255;
      const dx = Math.min(W - 1, Math.floor((sx / SAMPLE_W) * W));
      const dy = Math.min(H - 1, Math.floor((1 - luma) * (H - 1)));
      const o = (dy * W + dx) * 4;
      out[o] = Math.min(255, out[o] + 40);
      out[o + 1] = Math.min(255, out[o + 1] + 150);
      out[o + 2] = Math.min(255, out[o + 2] + 60);
      out[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}
