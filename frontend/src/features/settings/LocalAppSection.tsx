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
 * (开机自启、别的程序交来的文件怎么办),不是主题/语言/字体那种看的东西,也不是这一页别的行
 * 那种「连的是哪台后端」。谁读得到它们也相同 —— 只有桌面壳里才读得到。整页的分组见
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
          // 主进程把真实原因放在 info.error 里(GitHub 状态码、解析失败、网络错误)——
          // 带出来。光说「稍后再试」的话,代理挂了和真的没新版看上去一模一样。
          if (info.error) toast.error(t("updateCheckFailed"), { description: String(info.error) });
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

/**
 * 「本机应用」这一页:**这台电脑上 Mosael 自己的事**。
 *
 * 此前这三行挂在「后端」页里,而那一页的说明(settingsBackendDesc)只讲"连着的后端与工作区标识"——
 * 六行里只有两行是那件事,剩下三行(开机自启、别的程序交来的文件怎么办、版本与检查更新)说的都是
 * 这台机器上的应用行为。文档和内容对不上,于是维护者按「后端」去找服务器切换、按说明以为这一页
 * 都说后端。现在拆开:能切换的服务器、接口地址、工作区标识留在「后端」;这些回到自己的一页。
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
