import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { updatePluginInstance, type PluginNetwork } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { useDraftText } from "@/components/ui/draft-text";
import { SETTINGS_FIELD_WIDTH, SettingsRow } from "@/components/settings/settings-layout";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";

type Mode = PluginNetwork["mode"];

/**
 * 连接的**网络**:这个插件连接往外连走哪条路 —— 跟随 Mosael 的出站代理(默认)/ 直连 / 走它自己的代理。
 *
 * 是宿主给**每个**连接的一行,不是插件清单里的配置:走哪个代理是这台机器、这个人的网络状况,不是插件的
 * 业务。它和账号池里每个账号自己的代理同一个形状 —— 默认跟全局,单个可以覆盖。决定只在后端一处做
 * (backend domain/plugins/egress),插件子进程拿到的代理环境变量、后端替它发的请求都照那一个决定走。
 *
 * 选「走指定代理」时先长出地址框,**填好、离开框的时候才存**:没有地址的代理存不进去(后端会拒),
 * 也不该一选就发一次注定失败的请求。
 */
export function ConnectionNetwork({ instanceId, network }: { instanceId: string; network: PluginNetwork }) {
  const t = useI18n();
  const qc = useQueryClient();
  //: 选了「走指定代理」、地址还没存下来。存成功之后也不收:列表重新拉回来之前 `network` 还是旧的,
  //: 收了的话地址框会先消失一下再出来。换回跟随 / 直连时才收。
  const [choosingProxy, setChoosingProxy] = React.useState(false);
  const save = useMutation({
    mutationFn: (next: PluginNetwork) => updatePluginInstance(instanceId, { network: next }),
    onSuccess: () => invalidatePluginDependents(qc),
    // 「代理地址要写全」由后端说,原样转出来。
    onError: (error: Error) => toast.error(error.message),
  });
  const mode: Mode = choosingProxy ? "proxy" : network.mode;

  const choose = (next: string) => {
    if (next === "proxy") {
      if (network.mode !== "proxy") setChoosingProxy(true);
      return;
    }
    setChoosingProxy(false);
    if (next !== network.mode) save.mutate({ mode: next as Mode, proxy_url: "" });
  };

  return (
    <SettingsRow label={t("pluginNetwork")} description={t("pluginNetworkDesc")}>
      <SearchableSelect
        value={mode}
        onValueChange={choose}
        options={[
          { value: "follow", label: t("pluginNetworkFollow") },
          { value: "direct", label: t("pluginNetworkDirect") },
          { value: "proxy", label: t("pluginNetworkProxy") },
        ]}
      />
      {mode === "proxy" && (
        <ProxyAddress
          value={network.proxy_url}
          onCommit={(url) => {
            const next = url.trim();
            if (next && (next !== network.proxy_url || network.mode !== "proxy")) {
              save.mutate({ mode: "proxy", proxy_url: next });
            }
          }}
        />
      )}
    </SettingsRow>
  );
}

/** 代理地址框。草稿式、离开时才交(见 useDraftText):地址住在服务端,每敲一个字发一次请求会把字吞掉。 */
function ProxyAddress({ value, onCommit }: { value: string; onCommit: (value: string) => void }) {
  const t = useI18n();
  const draft = useDraftText<HTMLInputElement>({ value, onValueChange: onCommit, commit: "blur" });
  return (
    <Input
      className={SETTINGS_FIELD_WIDTH}
      aria-label={t("pluginNetworkProxyUrl")}
      placeholder="http://127.0.0.1:7890"
      autoFocus={!value}
      {...draft}
    />
  );
}
