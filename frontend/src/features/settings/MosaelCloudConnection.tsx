import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Cloud, RotateCw } from "lucide-react";
import { toast } from "sonner";

import {
  describeCloudFailure,
  getCloudAccount,
  loadCloudSession,
  syncCloudConnection,
} from "@/api/domains/cloud";
import type { ProviderProfile } from "@/api/domains/providers";
import { errorText } from "@/api/errorMessage";
import { cloudKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { SettingsListBlock, SettingsListItem } from "@/components/settings/settings-layout";
import { ProviderModelList } from "@/features/settings/ProviderModelList";
import { invalidateProviderDependents } from "@/features/settings/providerCaches";
import { gotoSettings } from "@/lib/deepLink";
import { cn } from "@/lib/utils";

/**
 * 供应商列表顶上那一行「Mosael Cloud」(ADR 0088)。
 *
 * **它是一条真的连接,但不在下面那张可编辑的列表里**:登录 MosaelCloud 时由后端建出来(`vendor = mosael-cloud`),
 * 钥匙是登录换来的设备令牌、端点跟着部署配置走、模型清单和积分单价由网关目录对齐 —— 名字、地址、密钥都没有可改的。
 * 所以它在这里单独画:登录了显示账号和积分,能展开模型、能「刷新」目录;没登录给「去登录」;这个部署关掉了 Cloud 就不出现。
 *
 * `profile` 是那条连接(还没建出来时为空 —— 登录那一刻网关没对上,点「刷新」就会建);`offersCapability` 说这一页的能力
 * (对话 / 生图 / …)网关有没有。没有的那几页只说「这类模型即将开放」。
 */
export function MosaelCloudConnection({
  profile,
  offersCapability,
}: {
  profile?: ProviderProfile | null;
  offersCapability: boolean;
}) {
  const session = useQuery({
    queryKey: cloudKeys.session(),
    queryFn: loadCloudSession,
    retry: false,
  });

  //: 关掉 Cloud 的部署、或者还没问出来:都不画。连不上 Cloud 不影响别的连接,这一行不替它报错。
  if (!session.isSuccess) {
    if (session.isError && !describeCloudFailure(session.error).notConfigured) return <SignedOutRow />;
    return null;
  }
  if (session.data === null) return <SignedOutRow />;
  return <SignedInRow email={session.data.email} profile={profile ?? null} offersCapability={offersCapability} />;
}

function SignedInRow({
  email,
  profile,
  offersCapability,
}: {
  email: string;
  profile: ProviderProfile | null;
  offersCapability: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [expanded, setExpanded] = React.useState(false);
  //: 积分每调用一次就少一点:不缓存太久,但也不为它轮询 —— 打开这一页、点刷新时各问一次。
  const account = useQuery({ queryKey: cloudKeys.account(), queryFn: getCloudAccount, retry: false, staleTime: 15_000 });
  const sync = useMutation({
    mutationFn: syncCloudConnection,
    onSuccess: ({ models }) => {
      invalidateProviderDependents(qc);
      void qc.invalidateQueries({ queryKey: cloudKeys.account() });
      toast.success(t("providerMosaelCloudSynced").replace("{n}", String(models)));
    },
    onError: (error) => toast.error(errorText(error)),
  });
  const credits = account.data ? t("providerMosaelCloudCredits").replace("{credits}", account.data.credits.toLocaleString()) : "";
  const showModels = offersCapability && profile !== null;

  return (
    <SettingsListBlock>
      <SettingsListItem data-mosael-cloud="" className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2">
        <CloudBadge />
        <div className="min-w-0">
          <Truncate as="strong" className="text-ui-md font-semibold">{t("providerMosaelCloud")}</Truncate>
          <Truncate as="small" className="text-ui-xs text-muted-foreground">
            {t("providerMosaelCloudSignedIn").replace("{email}", email)}
            {credits && ` · ${credits}`}
          </Truncate>
        </div>
        <div className="flex items-center gap-1">
          {offersCapability || profile === null ? null : <Badge variant="outline">{t("providerMosaelCloudSoon")}</Badge>}
          {showModels && (
            <IconButton
              size="icon-sm"
              label={t("modelListTitle")}
              aria-expanded={expanded}
              onClick={() => setExpanded((open) => !open)}
            >
              <ChevronDown size={13} className={cn("transition-transform", expanded && "rotate-180")} />
            </IconButton>
          )}
          <IconButton size="icon-sm" label={t("providerMosaelCloudRefresh")} loading={sync.isPending} onClick={() => sync.mutate()}>
            <RotateCw size={13} />
          </IconButton>
        </div>
        {showModels && expanded && (
          <div className="col-span-full border-t border-border pt-2">
            <ProviderModelList profileId={profile.id} vendor={profile.vendor} />
          </div>
        )}
      </SettingsListItem>
    </SettingsListBlock>
  );
}

function SignedOutRow() {
  const t = useI18n();
  return (
    <SettingsListBlock>
      <SettingsListItem data-mosael-cloud="" className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2">
        <CloudBadge />
        <div className="min-w-0">
          <Truncate as="strong" className="text-ui-md font-semibold">{t("providerMosaelCloud")}</Truncate>
          <Truncate as="small" className="text-ui-xs text-muted-foreground">{t("providerMosaelCloudSignedOut")}</Truncate>
        </div>
        <Button variant="ghost" size="sm" onClick={() => gotoSettings("account")}>
          {t("providerMosaelCloudSignIn")}
        </Button>
      </SettingsListItem>
    </SettingsListBlock>
  );
}

function CloudBadge() {
  return (
    <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-foreground">
      <Cloud size={13} />
    </span>
  );
}
