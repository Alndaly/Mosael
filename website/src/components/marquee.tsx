import { cn } from "@/lib/utils";

/**
 * 走马灯色带。
 *
 * 两段完全一样的内容首尾相接、整体左移 50% —— 到位时正好和起点重合,于是循环看不出接缝。
 * 这是纯 CSS 的一条动线:整站没有柔光、没有渐变,横向的运动是唯一的动感来源。
 *
 * 里面是一句话拆成的几个词,不是导航 —— 所以整条对读屏软件隐藏,不然会念出一串重复的碎词。
 */
export function Marquee({ items, className }: { items: string[]; className?: string }) {
  const track = [...items, ...items];

  return (
    <div
      aria-hidden
      className={cn("overflow-hidden border-y-2 border-ink bg-flame text-primary-foreground select-none", className)}
    >
      <div className="flex w-max animate-[marquee_38s_linear_infinite] motion-reduce:animate-none">
        {track.map((item, index) => (
          <span
            key={`${item}-${index}`}
            className="flex shrink-0 items-center gap-8 py-3 pr-8 text-sm font-bold tracking-widest uppercase"
          >
            {item}
            <span className="size-1.5 rotate-45 bg-primary-foreground" />
          </span>
        ))}
      </div>
    </div>
  );
}
