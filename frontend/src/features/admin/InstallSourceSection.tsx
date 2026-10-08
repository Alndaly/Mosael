import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { getInstallSource, updateInstallSource } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { PackageSourcePicker } from "@/components/settings/PackageSourcePicker";
import { SETTINGS_FIELD_WIDTH } from "@/components/settings/settings-layout";
import { useDraftText } from "@/components/ui/draft-text";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

/**
 * 管理 → 引擎 → 下载源(排在最前:先选从哪儿拉,再点下面各引擎的安装)。
 *
 * pip 给本机引擎(转写、声音克隆、人声分离一次拉 2–3 GB 的 Python 依赖,国内直连 PyPI 常常慢到不可用)
 * 和声明了 `package_sources: ["pypi"]` 的插件;npm 给声明了 `["npm"]` 的插件(Remotion)。插件连接上可以各自
 * 覆盖,没覆盖就跟随这里(见 backend domain/plugins/package_sources)。预设由后端给,界面不写死一张镜像表。
 *
 * 另两行给「让 Mosael 装」本机服务(ADR 0041 §4):**PyTorch 源**(Windows + NVIDIA 装 CUDA 版 PyTorch,pip 源管不到它;
 * 预设只收实测能当 simple 索引用的镜像)和 **GitHub 镜像前缀**(下钉死版本的压缩包;按 sha256 校验,镜像换不了内容)。
 *
 * **为什么在管理页**:往这台机器上装东西用哪个源,是部署级的设置,写入只给部署管理员
 * (routes/settings/system.set_install_source)。选中即保存:下拉换了就存,地址框离开时存。
 */
const MODEL_SOURCE_LABELS: Record<string, MessageKey> = {
  "hf-mirror": "settingsVoiceCloneSourceHfMirror",
  hf: "settingsVoiceCloneSourceHf",
  modelscope: "settingsVoiceCloneSourceModelscope",
};

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
        <AdminRow label={t("installSourcePytorch")} description={t("installSourcePytorchHint")}>
          <PackageSourcePicker
            ariaLabel={t("installSourcePytorch")}
            presets={source.data?.pytorch_presets ?? []}
            value={source.data?.pytorch_index ?? ""}
            onChange={(pytorch_index) => save.mutate({ pytorch_index })}
          />
        </AdminRow>
        <AdminRow label={t("installSourceGithub")} description={t("installSourceGithubHint")}>
          <GithubMirror value={source.data?.github_mirror ?? ""} onCommit={(github_mirror) => save.mutate({ github_mirror })} />
        </AdminRow>
        {/* 模型权重从哪儿下:此前藏在「声音克隆」里,却管着本机识别(NSFW)和 Mosael 起的本机 ComfyUI 的所有 HuggingFace
            下载(体检 UM-16)。数据到了才挂下拉:Radix Select 挂载之后从外部改 value 会回调一个空串,这里一回调就存。 */}
        <AdminRow label={t("voiceCloneSource")} description={t("installSourceModelHint")}>
          {source.data ? (
            <OptionPicker
              ariaLabel={t("voiceCloneSource")}
              className={SETTINGS_FIELD_WIDTH}
              value={source.data.model_source}
              onChange={(model_source) => model_source && model_source !== source.data?.model_source && save.mutate({ model_source })}
              options={(source.data.model_sources ?? []).map((id) => ({
                value: id,
                label: MODEL_SOURCE_LABELS[id] ? t(MODEL_SOURCE_LABELS[id]) : id,
              }))}
            />
          ) : null}
        </AdminRow>
      </div>
    </AdminSection>
  );
}

/** GitHub 镜像前缀:一个离开时才存的地址框(值住在服务端,每敲一个字发一次请求会把字吞掉);清空就是直连。 */
function GithubMirror({ value, onCommit }: { value: string; onCommit: (value: string) => void }) {
  const t = useI18n();
  const draft = useDraftText<HTMLInputElement>({
    value,
    onValueChange: (next) => {
      if (next.trim() !== value) onCommit(next.trim());
    },
    commit: "blur",
  });
  return (
    <Input
      className={SETTINGS_FIELD_WIDTH}
      aria-label={t("installSourceGithub")}
      placeholder={t("installSourceGithubPlaceholder")}
      spellCheck={false}
      {...draft}
    />
  );
}
