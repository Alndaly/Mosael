import React from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { API_BASE, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ServerPicker } from "@/components/layout/ServerPicker";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { SettingsGroup, SettingsRow, SettingsSectionStack } from "@/components/settings/settings-layout";

export function StartupRow() {
  const t = useI18n();
  const get = window.mosaelDesktop?.getOpenAtLogin;
  const set = window.mosaelDesktop?.setOpenAtLogin;
  // null = 还没问到;"unsupported" = 主进程说这个环境不提供(开发模式:execPath 是裸
  // Electron,写进登录项会污染开发机);其余是系统回读的状态。
  type State = { enabled: boolean; needsApproval: boolean };
  const [state, setState] = React.useState<State | null | "unsupported">(null);
  React.useEffect(() => {
    if (!get) return;
    void get().then((value) => setState(value ?? "unsupported"));
  }, [get]);
  if (!get || !set || state === "unsupported") return null;
  const settled = state === null ? null : state;
  return (
    <SettingsRow
      label={t("settingsStartup")}
      // **「要你去批准」不是「没开成」。** macOS 13 起这件事走 SMAppService:写进去之后
      // 系统会把它挂成待批准,而在批准之前回读到的仍是"没开"。此前界面据此把开关弹回去,
      // 用户看到的就是「点了没反应」——而系统设置里其实已经躺着一条待办。
      description={settled?.needsApproval ? t("settingsStartupNeedsApproval") : t("settingsStartupDesc")}
    >
      <Switch
        checked={settled?.enabled ?? false}
        disabled={state === null}
        // 用系统回读的值落地,而不是乐观置位:写登录项可能被系统策略拒绝(受管理的设备上
        // 常见),那时开关该弹回去,而不是显示成开着、实际没生效。
        onCheckedChange={(next) =>
          void set(next).then((value) => {
            setState(value ?? "unsupported");
            if (next && value && !value.enabled) toast.error(t("settingsStartupRefused"));
          })
        }
      />
    </SettingsRow>
  );
}

/** 检查更新(仅桌面端渲染):查 GitHub Releases 比对版本,发现新版给「查看」入口。
 *  未签名的 mac 包装不了静默自动安装,这里是诚实的降级——提示 + 打开发布页。 */
function UpdateCheckButton() {
  const t = useI18n();
  const [checking, setChecking] = React.useState(false);
  const check = window.mosaelDesktop?.checkUpdates;
  if (!check) return null;
  return (
    <Button
      size="xs"
      variant="outline"
      disabled={checking}
      onClick={async () => {
        setChecking(true);
        try {
          const info = await check();
          if (info.error) toast.error(t("updateCheckFailed"));
          else if (info.hasUpdate) {
            toast(t("updateAvailable").replace("{version}", info.latest ?? ""), {
              duration: 12000,
              action: { label: t("updateView"), onClick: () => window.open(info.url, "_blank") },
            });
          } else {
            // 带上比对到的版本号:光说「已是最新」在版本号本身有问题时毫无信息量,
            // 用户没法判断它到底比了什么。
            toast.success(`${t("updateUpToDate")} · v${info.latest ?? info.current ?? ""}`);
          }
        } finally {
          setChecking(false);
        }
      }}
    >
      {checking ? <Loader2 size={13} className="animate-mosael-spin" /> : <RefreshCw size={13} />}
      {t("updateCheck")}
    </Button>
  );
}


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
          <code className="timecode max-w-[320px] truncate text-xs text-muted-foreground">{API_BASE}</code>
        </SettingsRow>
        <SettingsRow label={t("settingsWorkspace")} description={t("settingsWorkspaceDesc")}>
          <code className="timecode max-w-[320px] truncate text-xs text-muted-foreground">{workspace.id}</code>
        </SettingsRow>
        <StartupRow />
        <SettingsRow label={t("settingsVersion")} description={t("settingsVersionDesc")}>
          <code className="timecode max-w-[320px] truncate text-xs text-muted-foreground">v{__APP_VERSION__}</code>
          <UpdateCheckButton />
        </SettingsRow>
      </SettingsGroup>
      {/* 出站代理不在这里:它是整台部署的出口,只有部署管理员能读写,归管理页的「部署设置」。 */}
    </SettingsSectionStack>
  );
}
