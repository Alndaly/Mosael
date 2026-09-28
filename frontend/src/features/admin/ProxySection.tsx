import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

type NetworkConfig = components["schemas"]["NetworkConfigOut"];

/**
 * 出站代理 —— 这台部署的后端怎么连出去。
 *
 * 在管理页而不在设置页:读写都只给部署管理员(routes/settings/system.py)。放在设置页时,普通成员
 * 读被拒、界面照样画出两个空框,读起来就是「直连」—— 一句错话。这里同理:**没读到就不给填**,
 * 空框只在真读到「空」时出现。
 */
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
  const unread = !config.data;

  return (
    <AdminSection
      id="proxy"
      title={t("proxyTitle")}
      description={t("proxyDesc")}
      actions={
        <Button size="sm" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
          {t("save")}
        </Button>
      }
    >
      <div className={ADMIN_CARD}>
        <AdminRow label={t("proxyUrl")} description={t("proxyUrlDesc")}>
          <Input
            className={SETTINGS_FIELD_WIDTH}
            aria-label={t("proxyUrl")}
            placeholder="http://127.0.0.1:7890"
            value={current.proxy_url}
            disabled={unread}
            onChange={(e) => setForm({ ...current, proxy_url: e.target.value })}
          />
        </AdminRow>
        {/* 回环强制直连这件事在说明里一句话讲清;不再另列一份「实际生效」—— 它几乎一字不差地重复上面这份。 */}
        <AdminRow label={t("proxyNoProxy")} description={t("proxyNoProxyDesc")} stacked>
          <Textarea
            className="min-h-32 font-mono text-ui-sm"
            aria-label={t("proxyNoProxy")}
            spellCheck={false}
            placeholder={"example.com\n10.0.0.0/8"}
            value={current.no_proxy}
            disabled={unread}
            onChange={(e) => setForm({ ...current, no_proxy: e.target.value })}
          />
        </AdminRow>
      </div>
    </AdminSection>
  );
}
