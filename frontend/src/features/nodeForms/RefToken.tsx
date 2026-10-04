import { AlertTriangle } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { refLabel, type RefLook } from "@/features/nodeForms/refCatalog";
import { refProblemText } from "@/features/nodeForms/refLook";
import { cn } from "@/lib/utils";

/**
 * **一个引用在屏幕上的样子**:「节点标题 · 输出显示名 · 子路径」的标签,悬停看存下去的那条路径;指不到东西时换错误色、
 * 带一枚警示,悬停说为什么。整格引用的下拉(RefCombobox 的触发器)和混写编辑器里的引用(RefEditor 的原子标签)
 * 都是它 —— 同一个引用在两处长得一样、说同一句话。
 */
export function RefToken({ path, look, chip = false, className }: { path: string; look: RefLook; chip?: boolean; className?: string }) {
  const t = useI18n();
  const problem = look.problem;
  return (
    <Hint label={problem ? refProblemText(t, problem) : path}>
    <span
      data-ref-token=""
      //: 编辑器里的那枚(整块选中、整块删除的原子标签)多带一个记号,测试和样式据此认它。
      data-ref-chip={chip ? "" : undefined}
      data-ref-problem={problem?.kind}
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-md px-1.5 py-px align-middle text-ui-2xs",
        problem
          ? "bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive"
          : "bg-[color-mix(in_srgb,var(--primary)_14%,transparent)] text-primary",
        className,
      )}
    >
      {problem && <AlertTriangle size={11} className="shrink-0" />}
      <Truncate>{refLabel(look)}</Truncate>
    </span>
    </Hint>
  );
}
