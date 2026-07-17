import { AlertTriangle, ArrowRight } from "lucide-react";

import { gotoSettings } from "@/lib/deepLink";

/** 「某项没配置 / 引用失效」的统一提示条:一句提醒 + 一个直达设置分区的配置入口。
 *  用在工作流节点、AI Studio 等任何依赖模型/服务但可能没配好的地方。 */
export function ConfigNotice({
  message,
  actionLabel,
  section,
  tone = "warn",
}: {
  message: string;
  actionLabel: string;
  /** 设置页分区 id(如 "providers");点「去配置」跳到那里。 */
  section: string;
  tone?: "warn" | "error";
}) {
  return (
    <div className={tone === "error" ? "config-notice is-error" : "config-notice"}>
      <AlertTriangle size={13} className="config-notice-icon" />
      <span className="config-notice-text">{message}</span>
      <button type="button" className="config-notice-action" onClick={() => gotoSettings(section)}>
        {actionLabel} <ArrowRight size={12} />
      </button>
    </div>
  );
}
