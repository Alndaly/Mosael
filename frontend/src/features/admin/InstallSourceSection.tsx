import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { getInstallSource, updateInstallSource } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { PackageSourcePicker } from "@/components/settings/PackageSourcePicker";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

/**
 * 管理 → 引擎 → 下载源(排在最前:先选从哪儿拉,再点下面各引擎的安装)。
 *
 * 两行:pip 给本机引擎(转写、声音克隆、人声分离一次拉 2–3 GB 的 Python 依赖,国内直连 PyPI 常常慢到不可用)
 * 和声明了 `package_sources: ["pypi"]` 的插件;npm 给声明了 `["npm"]` 的插件(Remotion)。插件连接上可以各自
 * 覆盖,没覆盖就跟随这里(见 backend domain/plugins/package_sources)。预设由后端给,界面不写死一张镜像表。
 *
 * **为什么在管理页**:往这台机器上装东西用哪个源,是部署级的设置,写入只给部署管理员
 * (routes/settings/system.set_install_source)。选中即保存:这里只有两个字段,再要求点一次「保存」只是多一步。
 */
export function InstallSourceSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const source = useQuery({ queryKey: ["install-source"], queryFn: getInstallSource });
  const save = useMutation({
    mutationFn: updateInstallSource,
    onSuccess: (next) => {
      qc.setQueryData(["install-source"], next);
      toast.success(t("saved"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <AdminSection id="install-source" title={t("installSourceTitle")} description={t("installSourceDesc")}>
      <div className={ADMIN_CARD}>
        <AdminRow label={t("voiceClonePipIndex")} description={t("installSourcePipIndexHint")}>
          <PackageSourcePicker
            ariaLabel={t("voiceClonePipIndex")}
            presets={source.data?.pip_presets ?? []}
            value={source.data?.pip_index ?? ""}
            onChange={(pip_index) => save.mutate({ pip_index })}
          />
        </AdminRow>
        <AdminRow label={t("installSourceNpm")} description={t("installSourceNpmHint")}>
          <PackageSourcePicker
            ariaLabel={t("installSourceNpm")}
            presets={source.data?.npm_presets ?? []}
            value={source.data?.npm_registry ?? ""}
            onChange={(npm_registry) => save.mutate({ npm_registry })}
          />
        </AdminRow>
      </div>
    </AdminSection>
  );
}
