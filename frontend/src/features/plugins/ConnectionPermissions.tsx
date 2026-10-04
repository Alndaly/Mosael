import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";

import { setPluginPermissions, type PluginInstance } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { SettingsBlock } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { describePermission } from "@/features/plugins/pluginPermissions";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";

/**
 * 这个连接**因为缺权限停着**时,在连接卡片的最上面说清楚:为什么停、缺哪几项(人话 + 原码)、点哪里恢复。
 *
 * 两种处境说法不同(后端给 `permissions_added`):
 * - 插件更新后多要了权限 —— 一个用得好好的连接突然停了。只说「权限未授予」的话,用户会以为插件坏了;
 *   这里说清楚是**新版多要的**、之前授予的不受影响、授予之后马上恢复;
 * - 刚接上的连接还没授权 —— 授予之后才能用。
 *
 * 一键授予的是**缺的这几项**,不碰已经授予的;下面逐项的权限开关照旧在。
 */
export function ConnectionPermissionNotice({ instance }: { instance: PluginInstance }) {
  const t = useI18n();
  const qc = useQueryClient();
  const pending = instance.pending_permissions ?? [];
  const grant = useMutation({
    mutationFn: () => setPluginPermissions(instance.id, { grants: Object.fromEntries(pending.map((one) => [one, true])) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["plugin-permissions", instance.id] });
      invalidatePluginDependents(qc);
    },
  });
  if (pending.length === 0) return null;
  const added = Boolean(instance.permissions_added);
  const count = String(pending.length);
  return (
    <SettingsBlock>
      <div role="alert" className="grid min-w-0 gap-3 rounded-lg border border-warning/40 bg-warning/5 p-4">
        <div className="flex min-w-0 items-start gap-2.5">
          <ShieldAlert size={16} className="mt-0.5 shrink-0 text-warning" aria-hidden />
          <div className="grid min-w-0 gap-1">
            <h4 className="m-0 text-ui-sm font-semibold text-foreground">
              {(added ? t("pluginPermAddedTitle") : t("pluginPermPendingTitle")).replace("{n}", count)}
            </h4>
            <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">
              {added ? t("pluginPermAddedBody") : t("pluginPermPendingBody")}
            </p>
          </div>
        </div>
        <ul className="m-0 grid list-none gap-1.5 p-0 pl-[26px]">
          {pending.map((permission) => (
            <li key={permission} className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-ui-sm text-foreground">
              <span>{describePermission(t, permission) ?? permission}</span>
              <span className="timecode text-ui-xs text-muted-foreground">{permission}</span>
            </li>
          ))}
        </ul>
        <div className="pl-[26px]">
          <Button loading={grant.isPending} onClick={() => grant.mutate()}>
            {t("pluginPermGrantAll").replace("{n}", count)}
          </Button>
        </div>
      </div>
    </SettingsBlock>
  );
}

/** 插件列表上要不要标「待授权」:有启用着的连接因为缺权限停了。 */
export function waitingForPermissions(instances: PluginInstance[]): boolean {
  return instances.some((instance) => instance.enabled && (instance.pending_permissions ?? []).length > 0);
}
