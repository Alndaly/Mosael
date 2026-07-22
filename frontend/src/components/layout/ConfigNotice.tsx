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
    <div className={cn(tone === "error" ? "config-notice is-error" : "config-notice", className)}>
      <AlertTriangle size={13} className="config-notice-icon" />
      <span className={cn("config-notice-text", textClassName)}>{message}</span>
      <button type="button" className={cn("config-notice-action", actionClassName)} onClick={() => gotoSettings(section)}>
        {actionLabel} <ArrowRight size={12} />
      </button>
    </div>
  );
}
