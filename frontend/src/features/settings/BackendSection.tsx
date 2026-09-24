import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { API_BASE, api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ServerPicker } from "@/components/layout/ServerPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { SETTINGS_FIELD_WIDTH, SettingsGroup, SettingsRow, SettingsSectionStack } from "@/components/settings/settings-layout";

type NetworkConfig = components["schemas"]["NetworkConfigOut"];

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

/** 出站代理。挂在「本地后端」下:它和端点、开机自启一样是实例级的基础设施设置,
 *  为一个字段单开一个导航项不值得。 */
export function ProxySection() {
  const t = useI18n();
  const qc = useQueryClient();
  const config = useQuery({
    queryKey: ["network-config"],
    queryFn: () => api<NetworkConfig>("/api/settings/network"),
  });
  // 绕过列表**一行一个**地编辑,存回去仍是逗号分隔(后端两种都认,见 domain/network)。
  // 此前是一个单行输入框装着九个逗号串起来的域名,只看得见前两个半,读起来像凭空冒出来的。
  const toLines = (value: string) => value.split(/[,，\n]/).map((one) => one.trim()).filter(Boolean).join("\n");
  const [form, setForm] = React.useState<{ proxy_url: string; no_proxy: string } | null>(null);
  const current = form ?? {
    proxy_url: config.data?.proxy_url ?? "",
    no_proxy: toLines(config.data?.no_proxy ?? ""),
  };
  const save = useMutation({
    mutationFn: () =>
      api<NetworkConfig>("/api/settings/network", {
        method: "PUT",
        body: JSON.stringify({ proxy_url: current.proxy_url.trim(), no_proxy: toLines(current.no_proxy).split("\n").join(", ") }),
      }),
    onSuccess: (next) => {
      setForm(null);
      qc.setQueryData(["network-config"], next);
    },
  });
  const dirty =
    form !== null &&
    (form.proxy_url !== (config.data?.proxy_url ?? "") || toLines(form.no_proxy) !== toLines(config.data?.no_proxy ?? ""));

  return (
    <SettingsGroup
      title={t("proxyTitle")}
      description={t("proxyDesc")}
      actions={
        <Button size="sm" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
          {t("save")}
        </Button>
      }
    >
      <SettingsRow label={t("proxyUrl")} description={t("proxyUrlDesc")}>
        <Input
          className={SETTINGS_FIELD_WIDTH}
          placeholder="http://127.0.0.1:7890"
          value={current.proxy_url}
          onChange={(e) => setForm({ ...current, proxy_url: e.target.value })}
        />
      </SettingsRow>
      {/* 此前还有一行「实际生效」:它只是上面这份列表再加上四个回环地址,几乎一字不差地重复了
          一遍,而且截断成一行 —— 读者看不出它和上面有什么不同。回环强制直连这件事在说明里一句话
          讲清就够了。保存键也不再挂在那一行上,移到这一节的抬头。 */}
      <SettingsRow label={t("proxyNoProxy")} description={t("proxyNoProxyDesc")} stacked>
        <Textarea
          className="min-h-32 font-mono text-ui-sm"
          spellCheck={false}
          placeholder={"example.com\n10.0.0.0/8"}
          value={current.no_proxy}
          onChange={(e) => setForm({ ...current, no_proxy: e.target.value })}
        />
      </SettingsRow>
    </SettingsGroup>
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
      {/* 出站代理不在这里了 —— 它和重试次数同一类(所有 AI 调用怎么出去),归「网络」一页。 */}
    </SettingsSectionStack>
  );
}
