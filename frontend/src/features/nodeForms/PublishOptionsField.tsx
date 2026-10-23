import React from "react";
import { useQuery } from "@tanstack/react-query";

import { listPublishAccounts, listPublishPlatforms, type PublishPlatform } from "@/api/domains/publish";
import { useI18n } from "@/app/preferences";
import { Combobox } from "@/components/app/combobox";
import { Switch } from "@/components/ui/switch";

/**
 * 发布节点的**平台选项**那一格(后端声明 `editor: "publish_options"`)。
 *
 * 为什么要一个专用控件:这一格的内容**跟着所选账号的平台变** —— 小红书有「原创声明」、抖音有
 * 「谁能看」,键名和取值由后端 `PUBLISH_PLATFORMS` 声明(发布页那张表单也是照这份声明画的)。
 * 通用编辑器只能给一个 `{}` 让用户背键名,而键名写错要等运行那一刻才知道。
 *
 * 所以这里取两样东西:账号列表(拿到这个账号属于哪个平台)与平台声明(拿到这个平台有哪些选项),
 * 然后把**和发布页同一批控件**画出来:
 * - `enum` → 下拉(取值就是声明里的 choices);
 * - `bool` → 开关。
 *
 * 账号还没选 / 平台还没取回来时,只写一句「先选账号」—— 不猜平台,也不假装有默认值。
 */
export function PublishOptionsField({
  workspaceId,
  accountId,
  value,
  onChange,
}: {
  workspaceId: string;
  /** 同一节点上的 `account_id` —— 选项跟随它。 */
  accountId: string;
  value: unknown;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const t = useI18n();
  const accounts = useQuery({
    queryKey: ["publish", "accounts", workspaceId],
    queryFn: () => listPublishAccounts(workspaceId),
    enabled: Boolean(workspaceId),
    staleTime: 30_000,
  });
  const platforms = useQuery({
    queryKey: ["publish", "platforms"],
    queryFn: () => listPublishPlatforms(),
    staleTime: 5 * 60_000,
  });

  const platformKey = (accounts.data ?? []).find((one) => one.id === accountId)?.platform ?? "";
  const platform: PublishPlatform | undefined = (platforms.data ?? []).find((one) => one.platform === platformKey);
  const stored = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;

  if (!accountId) {
    return <p className="text-ui-sm text-muted-foreground">{t("wfPublishOptionsPickAccount")}</p>;
  }
  if (accounts.isPending || platforms.isPending) {
    return <p className="text-ui-sm text-muted-foreground">{t("wfPublishOptionsLoading")}</p>;
  }
  const specs = platform?.options ?? [];
  if (!specs.length) {
    return <p className="text-ui-sm text-muted-foreground">{t("wfPublishOptionsNone")}</p>;
  }

  const set = (key: string, next: unknown) => {
    onChange({ ...stored, [key]: next });
  };

  return (
    <div className="grid gap-2">
      {specs.map((spec) => {
        const current = key_in(stored, spec.key) ? stored[spec.key] : spec.default;
        if (spec.type === "bool") {
          return (
            <label key={spec.key} className="flex items-center justify-between gap-3 rounded-md border border-field-border bg-field px-2.5 py-2">
              <span className="grid min-w-0 gap-0.5">
                <span className="text-ui-sm font-medium text-foreground">{spec.label}</span>
                {spec.description ? (
                  <small className="text-ui-xs leading-[1.4] text-muted-foreground">{spec.description}</small>
                ) : null}
              </span>
              <Switch checked={Boolean(current)} onCheckedChange={(next) => set(spec.key, next)} />
            </label>
          );
        }
        return (
          <label key={spec.key} className="grid gap-1">
            <span className="text-ui-sm font-medium text-foreground">{spec.label}</span>
            <Combobox
              className="w-full"
              value={String(current ?? "")}
              options={(spec.choices ?? []).map((choice) => ({ value: choice.value, label: choice.label }))}
              emptyText={t("cmdkEmpty")}
              onValueChange={(next) => set(spec.key, next)}
            />
            {spec.description ? (
              <small className="text-ui-xs leading-[1.4] text-muted-foreground">{spec.description}</small>
            ) : null}
          </label>
        );
      })}
    </div>
  );
}

const key_in = (row: Record<string, unknown>, key: string): boolean => Object.prototype.hasOwnProperty.call(row, key);
