import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

type Health = components["schemas"]["ProviderHealthOut"];

/**
 * 这条连接通不通、往返多久。
 *
 * **为什么值得占一个点**:配置错了和服务没起,此前在界面上是同一种表现 —— 什么都没有,
 * 直到真去生成一次才在任务失败里看到一句 502。本地类端点(ComfyUI / Ollama / LM Studio)
 * 最常见的故障就是"忘了启动",而这件事一秒钟就能测出来。
 *
 * **点进去才探,不轮询**:探针会真的打到用户自己的端点上,定时轮询等于替他持续产生请求 ——
 * 而"现在通不通"这个问题只在他看着这一页时才有意义。所以挂载时探一次,之后点它重探。
 */
export function ProviderHealth({ profileId, className }: { profileId: string; className?: string }) {
  const t = useI18n();
  const health = useQuery({
    queryKey: ["provider-health", profileId],
    queryFn: () => api<Health>(`/api/settings/providers/${profileId}/health`),
    // 探活结果几分钟内没必要重来;切回窗口也不重探(那会在用户只是切了个应用时打一串请求)。
    staleTime: 120_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  // 订阅计划没有我们持有的端点,探不了 —— 整块不显示,而不是显示一个假的"离线"。
  if (health.data && !health.data.supported) return null;

  const busy = health.isFetching;
  const online = health.data?.online ?? false;
  const latency = health.data?.latency_ms;
  const label = busy
    ? t("providerHealthChecking")
    : !health.data
      ? t("providerHealthUnknown")
      : online
        ? `${latency ?? "—"}ms`
        : t("providerHealthOffline");

  return (
    <button
      type="button"
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-ui-xs tabular-nums text-muted-foreground transition-colors hover:text-foreground",
        className,
      )}
      title={health.data?.detail || t("providerHealthRecheck")}
      onClick={(event) => {
        event.stopPropagation();
        void health.refetch();
      }}
    >
      {busy ? (
        <Loader2 size={9} className="animate-spin" />
      ) : (
        <span
          className={cn(
            "h-[6px] w-[6px] rounded-full bg-muted-foreground/50",
            health.data && (online ? "bg-success" : "bg-destructive"),
          )}
        />
      )}
      {label}
    </button>
  );
}
