"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 首页头部背后的一层星点:稀疏的小亮点各自慢慢明灭;鼠标经过时,附近几颗稍微亮一点、轻轻让开,
 * 划过的路上偶尔落下几颗细小的星屑,很快淡掉。
 *
 * 此前这里是两团漂浮的大光斑加一圈跟着鼠标走的 640px 光晕 —— 一大块颜色跟着指针挪,喧宾夺主
 * (用户:「一大块跟着走,我希望是星星点点那种感觉,不要太过浓妆艳抹」)。所以这里刻意克制:
 * 点小(1–2px)、透明度低、只在指针附近 140px 内起反应、星屑一次最多几十颗。
 *
 * 画在 canvas 上,每帧一次、不经过 React;不在视口里、页面切到后台时停帧。
 * 开了「减少动态效果」:只画一次静止的星点,不闪、不跟;触屏没有悬停,只闪不跟。
 */

type Star = { x: number; y: number; r: number; alpha: number; phase: number; speed: number; hue: number; ox: number; oy: number };
type Spark = { x: number; y: number; vx: number; vy: number; size: number; born: number; life: number; hue: number };

//: 品牌里的紫、紫粉、珊瑚(和标题渐变同一组),浅色背景上压深一点、深色背景上提亮一点。
const PALETTE = {
  light: ["90,67,234", "167,79,236", "240,120,110"],
  dark: ["190,176,255", "214,160,255", "255,176,160"],
};
const REACH = 140;
const MAX_SPARKS = 36;

export function StarField({ className }: { className?: string }) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    //: 指针在整块头部上都算(标题、按钮上也要有反应),canvas 自己不接事件。
    const host = canvas?.closest("section") ?? canvas?.parentElement;
    const context = canvas?.getContext("2d");
    if (!canvas || !host || !context) return;

    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const hover = window.matchMedia("(pointer: fine)").matches;
    let width = 0;
    let height = 0;
    let stars: Star[] = [];
    const sparks: Spark[] = [];
    let pointer: { x: number; y: number } | null = null;
    let lastSpawn: { x: number; y: number } | null = null;
    let frame = 0;
    let visible = true;

    const dark = () => document.documentElement.classList.contains("dark");

    const seed = () => {
      const box = canvas.getBoundingClientRect();
      width = box.width;
      height = box.height;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      //: 大约每 9000 平方像素一颗:一块 1400×900 的头部一百四十来颗,稀疏,不成片。
      const count = Math.round((width * height) / 9000);
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        r: 0.5 + Math.random() * 1.1,
        alpha: 0.12 + Math.random() * 0.3,
        phase: Math.random() * Math.PI * 2,
        speed: 0.4 + Math.random() * 0.9,
        hue: Math.floor(Math.random() * 3),
        ox: 0,
        oy: 0,
      }));
    };

    const drawSpark = (x: number, y: number, size: number, color: string, alpha: number) => {
      //: 四角星:两条细菱形交叉,比圆点更像「星」。
      context.fillStyle = `rgba(${color},${alpha})`;
      context.beginPath();
      context.moveTo(x, y - size);
      context.quadraticCurveTo(x, y, x + size, y);
      context.quadraticCurveTo(x, y, x, y + size);
      context.quadraticCurveTo(x, y, x - size, y);
      context.quadraticCurveTo(x, y, x, y - size);
      context.fill();
    };

    const draw = (now: number) => {
      const colors = dark() ? PALETTE.dark : PALETTE.light;
      context.clearRect(0, 0, width, height);
      const time = now / 1000;
      for (const star of stars) {
        let boost = 0;
        let tx = 0;
        let ty = 0;
        if (pointer) {
          const dx = star.x - pointer.x;
          const dy = star.y - pointer.y;
          const distance = Math.hypot(dx, dy);
          if (distance < REACH && distance > 0.01) {
            const pull = 1 - distance / REACH;
            boost = pull * 0.55;
            //: 轻轻让开,最多 6px:像被气流带了一下,不是被推开。
            tx = (dx / distance) * pull * 6;
            ty = (dy / distance) * pull * 6;
          }
        }
        star.ox += (tx - star.ox) * 0.08;
        star.oy += (ty - star.oy) * 0.08;
        const twinkle = still ? 1 : 0.65 + 0.35 * Math.sin(time * star.speed + star.phase);
        context.fillStyle = `rgba(${colors[star.hue]},${Math.min(1, star.alpha * twinkle + boost)})`;
        context.beginPath();
        context.arc(star.x + star.ox, star.y + star.oy, star.r + boost * 0.8, 0, Math.PI * 2);
        context.fill();
      }
      for (let index = sparks.length - 1; index >= 0; index -= 1) {
        const spark = sparks[index];
        const age = (now - spark.born) / spark.life;
        if (age >= 1) {
          sparks.splice(index, 1);
          continue;
        }
        spark.x += spark.vx;
        spark.y += spark.vy;
        //: 先亮后淡:前 20% 亮起,之后慢慢熄。
        const alpha = (age < 0.2 ? age / 0.2 : 1 - (age - 0.2) / 0.8) * 0.8;
        drawSpark(spark.x, spark.y, spark.size * (1 - age * 0.4), colors[spark.hue], alpha);
      }
    };

    const loop = (now: number) => {
      frame = 0;
      draw(now);
      if (visible && !document.hidden) frame = requestAnimationFrame(loop);
    };
    const start = () => {
      if (!frame && !still) frame = requestAnimationFrame(loop);
    };

    const move = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      const box = canvas.getBoundingClientRect();
      pointer = { x: event.clientX - box.left, y: event.clientY - box.top };
      //: 每划过 22px 才可能落一颗,六成概率 —— 星星点点,不是一条拖尾。
      if (!lastSpawn || Math.hypot(pointer.x - lastSpawn.x, pointer.y - lastSpawn.y) > 22) {
        lastSpawn = { ...pointer };
        if (Math.random() < 0.6 && sparks.length < MAX_SPARKS) {
          sparks.push({
            x: pointer.x + (Math.random() - 0.5) * 18,
            y: pointer.y + (Math.random() - 0.5) * 18,
            vx: (Math.random() - 0.5) * 0.25,
            vy: -0.1 - Math.random() * 0.25,
            size: 2.5 + Math.random() * 2,
            born: performance.now(),
            life: 900 + Math.random() * 500,
            hue: Math.floor(Math.random() * 3),
          });
        }
      }
      start();
    };
    const leave = () => {
      pointer = null;
      lastSpawn = null;
    };

    seed();
    draw(performance.now());
    const resize = new ResizeObserver(() => {
      seed();
      draw(performance.now());
    });
    resize.observe(canvas);
    const watch = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (visible) start();
    });
    watch.observe(canvas);
    const wake = () => {
      if (!document.hidden) start();
    };
    document.addEventListener("visibilitychange", wake);
    if (hover && !still) {
      host.addEventListener("pointermove", move, { passive: true });
      host.addEventListener("pointerleave", leave);
    }
    start();

    return () => {
      resize.disconnect();
      watch.disconnect();
      document.removeEventListener("visibilitychange", wake);
      host.removeEventListener("pointermove", move);
      host.removeEventListener("pointerleave", leave);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return <canvas ref={canvasRef} aria-hidden className={cn("pointer-events-none absolute inset-0 size-full", className)} />;
}
