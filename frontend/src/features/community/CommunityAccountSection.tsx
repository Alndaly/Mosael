import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Globe, LogOut, Link2 } from "lucide-react";
import { toast } from "sonner";

import {
  cancelCommunityConnect,
  communityPage,
  disconnectCommunity,
  getCommunityStatus,
  pollCommunityConnect,
  startCommunityConnect,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { COMMUNITY_STATUS_KEY, openInBrowser } from "@/features/community/communityShared";

/** 轮询设备授权的间隔。后端按社区给的 `interval` 节流,这里问得勤也不会多发请求。 */
const POLL_MS = 2000;

/**
 * 设置 →「社区账号」:把这台 Mosael 连到你的社区账号(ADR 0026 设备授权)。
 *
 * 四种状态:社区没配(部署设置里清空了)/ 没连 / 等你在浏览器里点「允许」/ 已连接为 @handle。
 * 连接时后端要一个设备码,这里用系统浏览器打开验证页,并把**配对码**大字显示出来 —— 网页上要核对它。
 * 令牌不经过这里:后端拿着、后端续期。
 */
export function CommunityAccountSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const status = useQuery({ queryKey: COMMUNITY_STATUS_KEY, queryFn: getCommunityStatus });
  const refresh = () => void qc.invalidateQueries({ queryKey: COMMUNITY_STATUS_KEY });

  const connect = useMutation({
    mutationFn: startCommunityConnect,
    onSuccess: (device) => {
      openInBrowser(device.verification_uri);
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const cancel = useMutation({ mutationFn: cancelCommunityConnect, onSettled: refresh });
  const disconnect = useMutation({
    mutationFn: disconnectCommunity,
    onSuccess: () => toast.success(t("communityDisconnected")),
    onError: (error: Error) => toast.error(error.message),
    onSettled: refresh,
  });

  const pending = status.data?.pending ?? null;
  React.useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(async () => {
      try {
        const result = await pollCommunityConnect();
        if (result.state === "pending") return;
        qc.setQueryData(COMMUNITY_STATUS_KEY, result.status);
        if (result.state === "connected") toast.success(t("communityConnectedToast").replace("{handle}", result.status.handle));
        else if (result.state === "expired") toast.error(t("communityConnectExpired"));
        else if (result.state === "denied") toast.error(t("communityConnectDenied"));
      } catch {
        /* 后端瞬断:下一轮再问 */
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
    // 换了一个码才重新起:同一个码的状态刷新不该把计时器重置。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending?.user_code]);

  const data = status.data;
  return (
    <SettingsGroup title={t("communityTitle")} description={t("communityDesc")}>
      {status.isPending ? (
        <div className="py-5">
          <Skeleton className="h-10 w-full" />
        </div>
      ) : !data || !data.configured ? (
        <SettingsRow label={t("communityNotConfigured")} description={t("communityNotConfiguredBody")} />
      ) : pending ? (
        <SettingsRow
          label={t("communityWaiting")}
          description={
            <span className="grid gap-2">
              <span>{t("communityWaitingBody")}</span>
              <code
                data-testid="community-user-code"
                className="timecode w-fit select-all rounded-md bg-panel-subtle px-3 py-1.5 text-ui-title font-semibold tracking-[0.2em] text-foreground"
              >
                {pending.user_code}
              </code>
              <small className="text-ui-xs text-muted-foreground">
                {t("communityCodeExpires").replace("{minutes}", String(Math.max(1, Math.ceil(pending.expires_in / 60))))}
              </small>
            </span>
          }
        >
          <span className="flex items-center gap-2">
            <Button variant="outline" onClick={() => openInBrowser(pending.verification_uri)}>
              <ExternalLink /> {t("communityOpenInBrowser")}
            </Button>
            <Button variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate()}>
              {t("cancel")}
            </Button>
          </span>
        </SettingsRow>
      ) : data.connected ? (
        <>
          <SettingsRow
            label={t("communityConnectedAs").replace("{handle}", data.handle)}
            description={[data.display_name, data.origin].filter(Boolean).join(" · ")}
          >
            <Button variant="outline" loading={disconnect.isPending} onClick={() => disconnect.mutate()}>
              <LogOut /> {t("communityDisconnect")}
            </Button>
          </SettingsRow>
          <SettingsRow label={t("communityMyPages")} description={t("communityMyPagesBody")}>
            <span className="flex items-center gap-2">
              <Button variant="ghost" asChild>
                <a href={communityPage(data.origin, "submissions")} target="_blank" rel="noreferrer noopener">
                  <Link2 /> {t("communityMySubmissions")}
                </a>
              </Button>
              <Button variant="ghost" asChild>
                <a href={communityPage(data.origin, "shares")} target="_blank" rel="noreferrer noopener">
                  <Link2 /> {t("communityMyShares")}
                </a>
              </Button>
            </span>
          </SettingsRow>
        </>
      ) : (
        <SettingsRow label={t("communityNotConnected")} description={t("communityNotConnectedBody").replace("{origin}", data.origin)}>
          <Button loading={connect.isPending} onClick={() => connect.mutate()}>
            <Globe /> {t("communityConnect")}
          </Button>
        </SettingsRow>
      )}
    </SettingsGroup>
  );
}
