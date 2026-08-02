import Image from "next/image";

import { imageSize } from "@/lib/media";
import { cn } from "@/lib/utils";

/**
 * 界面配图。
 *
 * 全站的截图和录屏都从这里出:同一套边框和留白,页面才不会一张图一个样。
 *
 * 尺寸默认从 public/ 下的文件头读(见 {@link imageSize})—— 文档正文里的 `![]()` 只给得出
 * 路径,而 next/image 要真实宽高来占位,填错了图会被拉变形。
 *
 * GIF 传 `unoptimized`:next/image 的优化管线不处理动图,不加这个参数会把多帧压成一张静态图,
 * 而"看得见它在动"正是这些录屏存在的理由。
 */
export function Shot({
  src,
  alt,
  width,
  height,
  caption,
  priority = false,
  framed = false,
  className,
}: {
  src: string;
  alt: string;
  width?: number;
  height?: number;
  caption?: string;
  priority?: boolean;
  /** 窗口壳:2px 墨边 + 实心偏移投影。首页那种大图用,文档正文里不用。 */
  framed?: boolean;
  className?: string;
}) {
  const size = width && height ? { width, height } : imageSize(src);
  const image = (
    <Image
      src={src}
      alt={alt}
      width={size.width}
      height={size.height}
      priority={priority}
      unoptimized={src.endsWith(".gif")}
      sizes="(min-width: 80rem) 80rem, 100vw"
      className={cn("h-auto w-full", framed ? "block" : "border-2 border-current bg-muted")}
    />
  );

  return (
    <figure className={cn("m-0", className)}>
      {framed ? (
        <div className="border-2 border-current bg-card shadow-block-lg">
          {/* 窗口顶栏。三颗灯是"这是一个桌面应用"最省字的说法。 */}
          <div className="flex h-8 items-center gap-2 border-b-2 border-ink bg-card px-3">
            <span className="size-2.5 rounded-full bg-flame" />
            <span className="size-2.5 rounded-full border-2 border-ink" />
            <span className="size-2.5 rounded-full border-2 border-ink" />
          </div>
          {image}
        </div>
      ) : (
        image
      )}
      {caption && <figcaption className="mt-4 text-sm opacity-70">{caption}</figcaption>}
    </figure>
  );
}
