import React from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { useI18n, usePreferences } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import { Truncate } from "@/components/ui/truncate";
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

/**
 * 外部打开的文件(访达 / 资源管理器的「打开方式」,或拖到程序坞 / 任务栏图标上)怎么办。
 *
 * **只在桌面壳里摆**:这条偏好说的是「别的程序把文件交给 Mosael」,而这件事的整条通道
 * (preload 转发 `mosael:open-files`,见 lib/deepLink)只在装了桌面壳时存在 —— 浏览器里改了它
 * 也没有任何东西会读。判据和上面那行 StartupRow 一模一样:桥不在就不摆。
 *
 * **和 StartupRow 挨着,而不是回「外观」**:这两行配的都是**这台机器上的桌面壳**行为
 * (开机自启、别的程序交来的文件怎么办),不是主题/语言/字体那种看的东西,也不是这一页剩下那行
 * 那种「这台安装现在是哪个版本」—— 那一行是只读的现状,这两行会改行为。谁读得到它们也相同 ——
 * 只有桌面壳里才读得到(版本那行浏览器里也看得到)。整页的分组见
 * features/settings/settingsSections(「系统」组)。
 */
export function ExternalOpenRow() {
  const t = useI18n();
  const { externalOpen, setExternalOpen } = usePreferences();
  if (!window.mosaelDesktop) return null;
  return (
    <SettingsRow label={t("settingsExternalOpen")} description={t("settingsExternalOpenDesc")}>
      <Segmented
        aria-label={t("settingsExternalOpen")}
        value={externalOpen}
        onValueChange={setExternalOpen}
        options={[
          { value: "import", label: t("settingsExternalOpenImport") },
          { value: "preview", label: t("settingsExternalOpenPreview") },
        ]}
      />
    </SettingsRow>
  );
}

/** 检查更新:打包版支持下载并静默安装,开发模式仍提供发布页入口。
 *  macOS 使用已签名/公证的 ZIP;Windows 使用 NSIS。安装前由主进程完成后端收尾。 */
type UpdateInfo = {
  current?: string;
  latest?: string;
  hasUpdate?: boolean;
  supportsAutoInstall?: boolean;
  phase?: string;
  percent?: number;
  url?: string;
  error?: string;
};

export function UpdateCheckButton() {
  const t = useI18n();
  const [busy, setBusy] = React.useState<"check" | "download" | "install" | null>(null);
  const [info, setInfo] = React.useState<UpdateInfo | null>(null);
  const check = window.mosaelDesktop?.checkUpdates;
  const download = window.mosaelDesktop?.downloadUpdate;
  const install = window.mosaelDesktop?.installUpdate;

  React.useEffect(() => {
    const offAvailable = window.mosaelDesktop?.onUpdateAvailable?.((next) => {
      if (next.hasUpdate) setInfo(next);
    });
    const offProgress = window.mosaelDesktop?.onUpdateProgress?.((next) => setInfo(next));
    return () => {
      offAvailable?.();
      offProgress?.();
    };
  }, []);

  if (!check) return null;

  const canInstall = Boolean(download && install && info?.supportsAutoInstall);
  const phase = info?.phase;
  const label =
    phase === "downloading"
      ? t("updateDownloading").replace("{percent}", String(info?.percent ?? 0))
      : phase === "downloaded"
        ? t("updateInstallNow")
        : info?.hasUpdate
          ? canInstall
            ? t("updateDownload")
            : t("updateView")
          : t("updateCheck");

  return (
    <Button
      size="xs"
      variant="outline"
      loading={busy !== null || phase === "downloading"}
      onClick={async () => {
        if (phase === "downloaded") {
          setBusy("install");
          try {
            const next = await install!();
            setInfo(next);
            if (next.error) toast.error(next.error);
          } finally {
            setBusy(null);
          }
          return;
        }
        if (info?.hasUpdate && canInstall) {
          setBusy("download");
          try {
            const next = await download!();
            setInfo(next);
            if (next.error) toast.error(t("updateDownloadFailed"), { description: String(next.error) });
          } finally {
            setBusy(null);
          }
          return;
        }
        if (info?.hasUpdate && !canInstall) {
          window.open(info.url, "_blank");
          return;
        }
        setBusy("check");
        try {
          const next = await check();
          setInfo(next);
          if (next.error) toast.error(t("updateCheckFailed"), { description: String(next.error) });
          else if (next.hasUpdate) {
            toast(t("updateAvailable").replace("{version}", next.latest ?? ""), {
              duration: 12000,
              action: {
                label: canInstall ? t("updateDownload") : t("updateView"),
                onClick: () => {
                  if (canInstall) void download!();
                  else window.open(next.url, "_blank");
                },
              },
            });
          } else {
            toast.success(`${t("updateUpToDate")} · v${next.latest ?? next.current ?? ""}`);
          }
        } finally {
          setBusy(null);
        }
      }}
    >
      {busy !== null || phase === "downloading" ? <Loader2 size={13} className="animate-mosael-spin" /> : <RefreshCw size={13} />}
      {label}
    </Button>
  );
}

/**
 * 「本机应用」这一页:**这台电脑上 Mosael 自己的事**。
 *
 * 此前这三行挂在「后端」页里,而那一页的说明(settingsBackendDesc)只讲"连着的后端与工作区标识"——
 * 六行里只有三行(服务器切换、接口地址、工作区标识)是那件事,剩下三行(开机自启、别的程序交来
 * 的文件怎么办、版本与检查更新)说的都是这台机器上的应用行为。文档和内容对不上,于是维护者按
 * 「后端」去找服务器切换、按说明以为这一页都说后端。现在拆开:能切换的服务器、接口地址、工作区
 * 标识留在「后端」;这些回到自己的一页。
 *
 * 分组不动 —— 两页都还在「连接与系统」组里挨着(system 那组讲的是这台客户端自己:飞书、宿主能力、
 * 连的后端、本机的应用行为)。
 */
export function LocalAppSection() {
  const t = useI18n();
  return (
    <SettingsSectionStack>
      <SettingsGroup title={t("settingsLocalAppTitle")} description={t("settingsLocalAppDesc")}>
        <StartupRow />
        <ExternalOpenRow />
        <SettingsRow label={t("settingsVersion")} description={t("settingsVersionDesc")}>
          <Truncate as="code" className="timecode max-w-[320px] text-xs text-muted-foreground">v{__APP_VERSION__}</Truncate>
          <UpdateCheckButton />
        </SettingsRow>
      </SettingsGroup>
    </SettingsSectionStack>
  );
}
