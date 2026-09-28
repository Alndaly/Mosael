import React from "react";
import { AlertTriangle, ArrowRight } from "lucide-react";

import { useIsDeploymentAdmin } from "@/app/auth";
import { useI18n } from "@/app/preferences";
import { gotoAdmin, gotoSettings } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

type NoticeLook = {
  message: string;
  tone?: "warn" | "error";
  className?: string;
  textClassName?: string;
};

/** 提示条的外壳:一句提醒(下面可再补一句)+ 右边一个出路。出路是什么由下面两种提示条各自决定。 */
function NoticeShell({
  message,
  detail,
  tone = "warn",
  className,
  textClassName,
  children,
}: NoticeLook & { detail?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className={cn(
      "flex items-start gap-1.5 rounded-lg border px-2.5 py-2 text-ui-xs leading-normal text-foreground",
      tone === "error"
        ? "border-[color-mix(in_oklab,var(--destructive)_45%,var(--border))] bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)]"
        : "border-[color-mix(in_oklab,var(--warning)_40%,var(--border))] bg-[color-mix(in_oklab,var(--warning)_10%,transparent)]",
      className,
    )}>
      <AlertTriangle size={13} className={cn("mt-px flex-none", tone === "error" ? "text-destructive" : "text-warning")} />
      {detail ? (
        <span className={cn("grid min-w-0 flex-1 gap-0.5", textClassName)}>
          <span>{message}</span>
          <span className="text-muted-foreground">{detail}</span>
        </span>
      ) : (
        <span className={cn("min-w-0 flex-1", textClassName)}>{message}</span>
      )}
      {children}
    </div>
  );
}

const ACTION_CLASS =
  "inline-flex flex-none cursor-pointer items-center gap-0.5 whitespace-nowrap border-0 bg-transparent p-0 text-ui-xs font-semibold text-primary hover:underline";

/** 「某项没配置 / 引用失效」的统一提示条:一句提醒 + 一个直达设置分区的配置入口。
 *  用在工作流节点、AI Studio 等任何依赖模型/服务但可能没配好的地方。 */
export function ConfigNotice({
  actionLabel,
  section,
  actionClassName,
  ...look
}: NoticeLook & {
  actionLabel: string;
  /** 设置页分区 id(如 "providers");点「去配置」跳到那里。 */
  section: string;
  actionClassName?: string;
}) {
  return (
    <NoticeShell {...look}>
      <button type="button" className={cn(ACTION_CLASS, actionClassName)} onClick={() => gotoSettings(section)}>
        {actionLabel} <ArrowRight size={12} />
      </button>
    </NoticeShell>
  );
}

/**
 * 「这台机器上还没装某个本机引擎」的提示条。
 *
 * 和 ConfigNotice 分开,是因为出路**因人而异**:装引擎只给部署管理员(转写、克隆、分离、降噪的
 * 安装接口都是 ensure_deployment_admin),入口在管理页「引擎」。管理员看到一个去那儿的按钮;
 * 成员看到一句「由部署管理员安装」—— 管理页对他没有入口,给他一个跳过去的按钮就是死路。
 */
export function EngineNotice(look: NoticeLook) {
  const t = useI18n();
  const isAdmin = useIsDeploymentAdmin();
  if (!isAdmin) return <NoticeShell {...look} detail={t("engineInstalledByAdmin")} />;
  return (
    <NoticeShell {...look}>
      <button type="button" className={ACTION_CLASS} onClick={() => gotoAdmin("engines")}>
        {t("engineGoInstall")} <ArrowRight size={12} />
      </button>
    </NoticeShell>
  );
}
