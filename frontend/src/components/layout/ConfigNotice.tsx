import { AlertTriangle, ArrowRight } from "lucide-react";

import { gotoSettings } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

/** 「某项没配置 / 引用失效」的统一提示条:一句提醒 + 一个直达设置分区的配置入口。
 *  用在工作流节点、AI Studio 等任何依赖模型/服务但可能没配好的地方。 */
export function ConfigNotice({
  message,
  actionLabel,
  section,
  tone = "warn",
  className,
  textClassName,
  actionClassName,
}: {
  message: string;
  actionLabel: string;
  /** 设置页分区 id(如 "providers");点「去配置」跳到那里。 */
  section: string;
  tone?: "warn" | "error";
  className?: string;
  textClassName?: string;
  actionClassName?: string;
}) {
  return (
    <div className={cn(
      "flex items-start gap-1.5 rounded-lg border px-2.5 py-2 text-ui-xs leading-normal text-foreground",
      tone === "error"
        ? "border-[color-mix(in_oklab,var(--destructive)_45%,var(--border))] bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)]"
        : "border-[color-mix(in_oklab,var(--warning)_40%,var(--border))] bg-[color-mix(in_oklab,var(--warning)_10%,transparent)]",
      className,
    )}>
      <AlertTriangle size={13} className={cn("mt-px flex-none", tone === "error" ? "text-destructive" : "text-warning")} />
      <span className={cn("min-w-0 flex-1", textClassName)}>{message}</span>
      <button type="button" className={cn("inline-flex flex-none cursor-pointer items-center gap-0.5 whitespace-nowrap border-0 bg-transparent p-0 text-ui-xs font-semibold text-primary hover:underline", actionClassName)} onClick={() => gotoSettings(section)}>
        {actionLabel} <ArrowRight size={12} />
      </button>
    </div>
  );
}
