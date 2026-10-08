import React from "react";
import { AlertTriangle } from "lucide-react";

import { useI18n } from "@/app/preferences";
import type { TwoLayerName } from "@/lib/entryNames";
import { cn } from "@/lib/utils";

/**
 * 记着的生成模型现在用不了(ADR 0045 修订之一):说**记着的那个**叫什么(两层)、为什么,下面是出路 —— 修好它(调用方给:
 * ComfyUI 的「去工作流库升级」)和「换一个模型」。会话、画板格子、工作流节点同一个样子。
 *
 * 不说「选择模型」,也不拿别的模型顶上:顶上的那个和用户以为在用的不是同一个,点发送花的是别家的钱。
 */
export function MissingModelNote({
  names,
  reason,
  pending,
  actions,
  className,
}: {
  names: TwoLayerName;
  /** 为什么(后端按看的人的语言挑好);还在问是 null */
  reason: string | null;
  pending: boolean;
  actions?: React.ReactNode;
  className?: string;
}) {
  const t = useI18n();
  return (
    <div
      role="alert"
      data-model-missing=""
      className={cn(
        "grid min-w-0 gap-1 rounded-lg border px-2.5 py-2 text-ui-xs leading-relaxed text-foreground",
        "border-[color-mix(in_oklab,var(--warning)_40%,var(--border))] bg-[color-mix(in_oklab,var(--warning)_10%,transparent)]",
        className,
      )}
    >
      <p className="m-0 flex min-w-0 items-start gap-1.5 font-medium">
        <AlertTriangle size={13} className="mt-0.5 flex-none text-warning" aria-hidden />
        <span className="min-w-0 break-words">{t("genModelMissingTitle").replace("{model}", names.primary)}</span>
      </p>
      {names.secondary && <p className="m-0 min-w-0 break-words pl-[19px] text-muted-foreground">{names.secondary}</p>}
      <p className="m-0 min-w-0 break-words pl-[19px] text-muted-foreground" data-model-missing-reason="">
        {pending || !reason ? t("genModelMissingChecking") : reason}
      </p>
      {actions && <div className="flex flex-wrap items-center gap-1.5 pl-[19px] pt-0.5">{actions}</div>}
    </div>
  );
}
