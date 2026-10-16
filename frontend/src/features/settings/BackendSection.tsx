import { API_BASE, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ServerPicker } from "@/components/app/ServerPicker";
import { Truncate } from "@/components/ui/truncate";
import { SettingsGroup, SettingsRow, SettingsSectionStack } from "@/components/settings/settings-layout";

function ServerSwitchRow() {
  const t = useI18n();
  return (
    <SettingsRow label={t("serverSwitchLabel")} description={t("serverSwitchDesc")}>
      <ServerPicker />
    </SettingsRow>
  );
}

export function BackendSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  return (
    <SettingsSectionStack>
      <SettingsGroup title={t("settingsBackend")} description={t("settingsBackendDesc")}>
        <ServerSwitchRow />
        <SettingsRow label={t("settingsEndpoint")} description={t("settingsEndpointDesc")}>
          <Truncate as="code" className="timecode max-w-[320px] text-xs text-muted-foreground">{API_BASE}</Truncate>
        </SettingsRow>
        <SettingsRow label={t("settingsWorkspace")} description={t("settingsWorkspaceDesc")}>
          <Truncate as="code" className="timecode max-w-[320px] text-xs text-muted-foreground">{workspace.id}</Truncate>
        </SettingsRow>
      </SettingsGroup>
      {/* 开机自启 / 打开外部文件 / 版本与检查更新不在这一页:那三行说的是这台电脑上的应用行为,
          归「本机应用」(features/settings/LocalAppSection)。 */}
      {/* 出站代理不在这里:它是整台部署的出口,只有部署管理员能读写,归管理页的「部署设置」。 */}
    </SettingsSectionStack>
  );
}
