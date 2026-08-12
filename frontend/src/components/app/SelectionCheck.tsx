import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 卡片左上角的勾选圈 —— **只有这一种**。
 *
 * 素材、发布记录、工作流三处都要,长得不一样的话"选中"这件事在同一个应用里就有三种样子。
 * 位置也一并定死(左上角、z-[2]、pointer-events-none):它压在卡片上,点击由卡片本身接。
 */
export function SelectionCheck({ selected, className }: { selected: boolean; className?: string }) {
  return (
    <span
      className={cn(
        "pointer-events-none absolute left-2 top-2 z-[2] grid size-5 place-items-center rounded-full border",
        selected ? "border-primary bg-primary text-primary-foreground" : "border-border-strong bg-panel text-transparent",
        className,
      )}
    >
      <Check size={12} />
    </span>
  );
}
