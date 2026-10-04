"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * 一段静音循环的录屏,替代原来的 GIF。
 *
 * - **进了视口才加载、才播**:`preload="none"`,IntersectionObserver 看见它才 `play()`,滚出去就停。
 *   深浅两套里藏着的那一个(`display: none`)永远不会和视口相交,也就永远不下载。
 * - **尊重「减少动态效果」**:系统开了这一项时不自动播,露出原生控件 —— 看到的是封面截图和播放键,
 *   想看再点。设置在页面打开期间改了也跟着变。
 */
export function LoopVideo({ src, poster, label, className }: {
  src: string;
  poster: string;
  label: string;
  className?: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const [still, setStill] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setStill(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    if (still) {
      video.pause();
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          // 浏览器可能拒绝(省电模式之类):那就停在封面上,不报错。
          video.play().catch(() => {});
        } else {
          video.pause();
        }
      },
      { threshold: 0.25 },
    );
    observer.observe(video);
    return () => observer.disconnect();
  }, [still]);

  return (
    <video
      ref={ref}
      muted
      loop
      playsInline
      preload="none"
      poster={poster}
      controls={still}
      aria-label={label}
      className={cn("aspect-[8/5] h-auto w-full rounded-xl border border-border/80 bg-muted", className)}
    >
      <source src={src} type="video/mp4" />
    </video>
  );
}
