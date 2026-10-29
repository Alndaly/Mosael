import { useQuery } from "@tanstack/react-query";
import { Cloud } from "lucide-react";

import { describeCloudFailure, loadCloudSession } from "@/api/domains/cloud";
import { cloudKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Truncate } from "@/components/ui/truncate";
import { SettingsListBlock, SettingsListItem } from "@/components/settings/settings-layout";
import { gotoSettings } from "@/lib/deepLink";

/**
 * 供应商列表顶上那一行「Mosael Cloud」(ADR 0088 第 1 步;ADR 0039 待拍板 #7)。
 *
 * **不是一条可增删的连接**:它跟着「设置 → 账户」里的 MosaelCloud 登录走 —— 登录即有,不需要填密钥。
 * 没登录时也列出来,点「去登录」跳到账户页;这个部署关掉了 Cloud(`cloud_not_configured`)就不出现,
 * 免得给一条点了只会错的路。网关的模型目录在第 2 步上线,在那之前右侧只说「即将开放」。
 */
export function MosaelCloudConnection() {
  const t = useI18n();
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

  return (
    <SettingsListBlock>
      <SettingsListItem data-mosael-cloud="" className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2">
        <CloudBadge />
        <div className="min-w-0">
          <Truncate as="strong" className="text-ui-md font-semibold">{t("providerMosaelCloud")}</Truncate>
          <Truncate as="small" className="text-ui-xs text-muted-foreground">
            {t("providerMosaelCloudSignedIn").replace("{email}", session.data.email)}
          </Truncate>
        </div>
        <Badge variant="outline">{t("providerMosaelCloudSoon")}</Badge>
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
