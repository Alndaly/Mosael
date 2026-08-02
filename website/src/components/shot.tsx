import Image from "next/image";

import { imageSize } from "@/lib/media";
import { cn } from "@/lib/utils";

/**
 * 界面配图。
 *
 * 全站的截图和录屏都从这里出:同一套边框、圆角和留白,页面才不会一张图一个样。
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
  className,
}: {
  src: string;
  alt: string;
  width?: number;
  height?: number;
  caption?: string;
  priority?: boolean;
  className?: string;
}) {
  const size = width && height ? { width, height } : imageSize(src);

  return (
    <figure className={cn("m-0", className)}>
      <Image
        src={src}
        alt={alt}
        width={size.width}
        height={size.height}
        priority={priority}
        unoptimized={src.endsWith(".gif")}
        sizes="(min-width: 64rem) 64rem, 100vw"
        className="h-auto w-full rounded-xl border border-border/70 bg-muted"
      />
      {caption && <figcaption className="mt-3 font-sans text-sm text-muted-foreground">{caption}</figcaption>}
    </figure>
  );
}
