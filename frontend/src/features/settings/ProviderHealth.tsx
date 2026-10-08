import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { probeProviderHealth } from "@/api/client";
import { providerKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { Hint } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";


/**
 * 这条连接通不通、往返多久。
 *
 * **为什么值得占一个点**:配置错了和服务没起,此前在界面上是同一种表现 —— 什么都没有,
 * 直到真去生成一次才在任务失败里看到一句 502。本地类端点(Ollama / LM Studio)
 * 最常见的故障就是"忘了启动",而这件事一秒钟就能测出来。
 *
 * **点进去才探,不轮询**:探针会真的打到用户自己的端点上,定时轮询等于替他持续产生请求 ——
 * 而"现在通不通"这个问题只在他看着这一页时才有意义。所以挂载时探一次,之后点它重探。
 */
export function ProviderHealth({
  profileId,
  className,
  usable = true,
}: {
  profileId: string;
  className?: string;
  /** 这条连接对我能不能用(钥匙填了、授权了)。地址通而我用不了时,圆点不用成功色 —— 此前缺密钥的连接旁边亮着绿色的
   *  「275ms」,读起来像「连上了」(体检 UM-23)。 */
  usable?: boolean;
}) {
  const t = useI18n();
  const health = useQuery({
    queryKey: providerKeys.health(profileId),
    queryFn: () => probeProviderHealth(profileId),
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
    // 第一行说点了会怎样,第二行是探测回来的细节(哪儿不通、多慢)。
    <Hint label={t("providerHealthRecheck")} hint={online && !usable ? t("providerHealthReachableNotUsable") : health.data?.detail}>
    <button
      type="button"
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-ui-xs tabular-nums text-muted-foreground transition-colors hover:text-foreground",
        className,
      )}
      onClick={(event) => {
        event.stopPropagation();
        void health.refetch();
      }}
    >
      {busy ? (
        <Loader2 size={9} className="animate-spin" />
      ) : (
        <span
          data-health-dot={health.data ? (online ? (usable ? "online" : "reachable") : "offline") : "unknown"}
          className={cn(
            "h-[6px] w-[6px] rounded-full bg-muted-foreground/50",
            health.data && (online ? (usable ? "bg-success" : "bg-muted-foreground/50") : "bg-destructive"),
          )}
        />
      )}
      {label}
    </button>
    </Hint>
  );
}
