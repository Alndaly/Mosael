import { Plus } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 「再加一行」—— **一条撑满的虚线空位**,不是挂在列表末尾的一枚幽灵小钮。
 *
 * 判据是它要长得像**它将要变成的那个东西**:点下去出现的是一整行,所以它本身就该占一整行。
 * 此前它是一枚左对齐的 ghost 按钮,没有边界也没有底色 —— 一行都没有的时候,它悬在一大片
 * 空白里,既读不出是可点的,也读不出它和上面那格是什么关系,只看得出"这里的间距不对劲"。
 *
 * 虚线是"这里还空着"的通用说法(和实线的字段区分开),所以它不会被误读成又一格要填的表单。
 *
 * 高度跟着所在表单的刻度:`dense` 是密排的检查器那一档(h-8),默认是设置里的字段档(h-10)。
 */
export function AddRow({
  label,
  onClick,
  dense,
  className,
}: {
  label: string;
  onClick: () => void;
  dense?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full cursor-pointer items-center justify-center gap-1.5 rounded-md border border-dashed border-border bg-panel/60 text-muted-foreground transition-colors hover:border-border-strong hover:bg-secondary hover:text-foreground",
        dense ? "h-8 text-ui-xs" : "h-10 text-ui-sm",
        className,
      )}
    >
      <Plus size={dense ? 12 : 13} />
      {label}
    </button>
  );
}
