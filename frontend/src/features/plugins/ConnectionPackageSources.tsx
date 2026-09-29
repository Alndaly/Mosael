import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { updatePluginInstance, type PluginInstance } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { PackageSourcePicker } from "@/components/settings/PackageSourcePicker";
import { SettingsRow } from "@/components/settings/settings-layout";
import { invalidatePluginDependents } from "@/features/plugins/pluginCaches";

/**
 * 连接的**包镜像**:这个插件装依赖从哪个镜像拉。清单里声明了哪几个生态(`package_sources`)就有哪几行,
 * 默认跟随「管理 → 下载源」,单个连接可以覆盖 —— 和上面「网络」那一行同一个形状。
 *
 * 是宿主给的一行,不是插件自带的配置项:此前 Manim、Remotion 各带一个自由文本的镜像框,每个插件各存一份地址,
 * 和管理页的下载源互不知道(用户截图:「镜像应该是下拉选择而不是输入」)。决定只在后端一处
 * (backend domain/plugins/package_sources),按各生态自己认的变量名注入插件进程。
 */
export function ConnectionPackageSources({ instanceId, sources }: {
  instanceId: string;
  sources: NonNullable<PluginInstance["package_sources"]>;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (choice: Record<string, string>) => updatePluginInstance(instanceId, { package_sources: choice }),
    onSuccess: () => invalidatePluginDependents(qc),
    // 「镜像地址要以 http(s):// 开头」由后端说,原样转出来。
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <>
      {sources.map((row) => (
        <SettingsRow key={row.source} label={row.label} description={t("pkgSourceDesc")}>
          <PackageSourcePicker
            ariaLabel={row.label}
            presets={row.presets ?? []}
            value={row.value ?? ""}
            followLabel={row.host_label ?? ""}
            onChange={(value) => save.mutate({ [row.source]: value })}
          />
        </SettingsRow>
      ))}
    </>
  );
}
