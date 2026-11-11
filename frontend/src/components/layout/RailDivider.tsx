import { cn } from "@/lib/utils";

/**
 * 侧栏里的分隔线:**全部同一条** —— 左右各缩 8px(和导航项的圆角底色对齐),上下各留 12px(段间那一档)。
 *
 * 此前三处各写各的:快捷键条下面那条贯穿整宽、上下 12px;导航里的两条缩 8px、`my-3` 再叠上导航项之间 4px 的 gap,
 * 实际上下各 16px;底部那条又是整宽。维护者截图:「这里间距似乎有点不太一致」。
 *
 * `inNav`:画在导航列表里(它的子项之间有 4px gap,矮屏 2px),margin 扣掉 gap,看上去照样是 12px(矮屏 8px)。
 */
export function RailDivider({ inNav = false }: { inNav?: boolean }) {
  return (
    <div
      data-rail-divider=""
      className={cn(
        "mx-2 shrink-0 border-t border-divider",
        inNav ? "my-2 [@media(max-height:850px)]:my-1.5" : "my-3 [@media(max-height:850px)]:my-2",
      )}
    />
  );
}
