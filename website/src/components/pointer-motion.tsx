"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 首页跟着鼠标动的那几处(光晕、截图视差、卡片倾斜)共用的一件事:**把指针位置写成 CSS 变量**,
 * 样式全在 className 里读变量,React 不因为鼠标移动重渲染一次。
 *
 * 写进元素的变量:
 * - `--pointer-x` / `--pointer-y`:指针在元素里的位置(px),给光晕、高光定圆心;
 * - `--tilt-x` / `--tilt-y`:同一位置折成 -1…1(中心是 0),给倾斜、视差乘系数用;
 * - `data-pointer="on"`:指针在元素上 —— 离开时变量归零,配合 transition 平滑回正。
 *
 * **只在有精确指针、且没开「减少动态效果」时生效**:触屏上没有悬停这回事,手指一碰就倾斜只会
 * 让人以为点错了;开了减少动效的人看到的就是静态页面。
 * 每帧最多写一次(requestAnimationFrame 合并 pointermove),子元素照常读变量,不另挂监听。
 */
function usePointerVariables(ref: React.RefObject<HTMLElement | null>) {
  React.useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const allowed = window.matchMedia("(pointer: fine) and (prefers-reduced-motion: no-preference)");
    let frame = 0;
    let last: PointerEvent | null = null;

    const write = () => {
      frame = 0;
      if (!last) return;
      const box = node.getBoundingClientRect();
      const x = last.clientX - box.left;
      const y = last.clientY - box.top;
      node.style.setProperty("--pointer-x", `${x}px`);
      node.style.setProperty("--pointer-y", `${y}px`);
      node.style.setProperty("--tilt-x", ((x / box.width) * 2 - 1).toFixed(3));
      node.style.setProperty("--tilt-y", ((y / box.height) * 2 - 1).toFixed(3));
    };
    const move = (event: PointerEvent) => {
      if (!allowed.matches || event.pointerType !== "mouse") return;
      last = event;
      node.dataset.pointer = "on";
      if (!frame) frame = requestAnimationFrame(write);
    };
    const leave = () => {
      last = null;
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      delete node.dataset.pointer;
      node.style.setProperty("--tilt-x", "0");
      node.style.setProperty("--tilt-y", "0");
    };

    node.addEventListener("pointermove", move, { passive: true });
    node.addEventListener("pointerleave", leave);
    return () => {
      node.removeEventListener("pointermove", move);
      node.removeEventListener("pointerleave", leave);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ref]);
}

/** 一块感应指针的区域。子元素用 `var(--pointer-x)`、`var(--tilt-x)` 这些变量自己决定怎么动。 */
export function PointerSurface({
  children,
  className,
  id,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
  as?: "div" | "section";
}) {
  const ref = React.useRef<HTMLElement>(null);
  usePointerVariables(ref);
  return (
    <Tag ref={ref as never} id={id} className={cn("group/pointer [--tilt-x:0] [--tilt-y:0]", className)}>
      {children}
    </Tag>
  );
}

/**
 * 朝指针方向微微倾斜的卡片,表面带一道跟着指针走的高光 —— 像拿在手里的一张照片。
 *
 * 角度刻意压得很小(默认 4°):截图是要读的,倾得太狠字就斜了。移开后 600ms 缓回平面;
 * 跟随时只用 150ms 的过渡,手感是「跟着」而不是「拖着」。
 */
export function TiltCard({ children, className, max = 4 }: { children: React.ReactNode; className?: string; max?: number }) {
  const ref = React.useRef<HTMLDivElement>(null);
  usePointerVariables(ref);
  return (
    <div ref={ref} className={cn("group/tilt [--tilt-x:0] [--tilt-y:0] [perspective:1400px]", className)}>
      <div
        style={{ "--tilt-max": `${max}deg` } as React.CSSProperties}
        className={cn(
          "relative transition-transform duration-[600ms] ease-[cubic-bezier(0.16,1,0.3,1)]",
          "[transform:rotateX(calc(var(--tilt-y)*var(--tilt-max)*-1))_rotateY(calc(var(--tilt-x)*var(--tilt-max)))]",
          "group-data-[pointer=on]/tilt:duration-150",
        )}
      >
        {children}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-[1.5rem] opacity-0 mix-blend-soft-light transition-opacity duration-500 group-data-[pointer=on]/tilt:opacity-100 bg-[radial-gradient(520px_circle_at_var(--pointer-x)_var(--pointer-y),rgba(255,255,255,0.5),transparent_55%)]"
        />
      </div>
    </div>
  );
}
