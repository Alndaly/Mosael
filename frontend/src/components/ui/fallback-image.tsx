import * as React from "react";
import { ImageOff } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * **一张会失败的图**。
 *
 * 界面上几乎所有图都可能读不出来:素材文件被清理、缩略图没生成、远端预览地址过期、
 * 头像被换掉、截图丢了。裸 `<img>` 在那种时候画的是浏览器的破图图标 —— 既没说是什么,
 * 也没说为什么(2026-10-23 素材卡片、2026-10-24 设置页头像都是这么被指出来的)。
 *
 * 这一层只做一件事:**加载失败就换成一块说明**,由调用方给占位形状(图标 / 文字 / 尺寸)。
 * 不再每个地方自己写一遍 `onError` + 状态。
 */
export function FallbackImage({
  src,
  alt = "",
  className,
  fallbackClassName,
  fallback,
  onBroken,
  ...rest
}: {
  src: string;
  alt?: string;
  /** 图本身的类名(尺寸 / 圆角 / object-fit 写在这里)。 */
  className?: string;
  /** 占位块额外加在**容器**上的类名(它和图同尺寸,因为容器就是图那一格)。 */
  fallbackClassName?: string;
  /** 占位内容;不给就是一枚中性图标。 */
  fallback?: React.ReactNode;
  /** 失败时的回调(日志 / 统计)。 */
  onBroken?: () => void;
} & Omit<React.ImgHTMLAttributes<HTMLImageElement>, "src" | "alt" | "className" | "onError">) {
  const [broken, setBroken] = React.useState(false);
  //: 换了地址就重新试一次 —— 上一个文件取不到,不代表新地址也取不到(「换一张预览图」就是这条路)。
  React.useEffect(() => {
    setBroken(false);
  }, [src]);

  if (broken) {
    return (
      <span
        data-image-fallback=""
        role="img"
        aria-label={alt || undefined}
        className={cn(
          "grid place-items-center bg-workspace-subtle text-muted-foreground",
          className,
          fallbackClassName,
        )}
      >
        {fallback ?? <ImageOff size={16} aria-hidden />}
      </span>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      onError={() => {
        setBroken(true);
        onBroken?.();
      }}
      {...rest}
    />
  );
}
