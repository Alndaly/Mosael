import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { getInstallSource, updateInstallSource } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { OptionPicker } from "@/components/ui/option-picker";
import { SETTINGS_FIELD_WIDTH, SettingsGroup, SettingsRow } from "@/components/settings/settings-layout";

/** 预设的镜像 key。空串 = 官方 PyPI(后端据此不传 --index-url)。 */
const PRESETS = ["pypi", "tsinghua", "aliyun", "tencent"] as const;

/**
 * Settings → 本机引擎 → 安装源。
 *
 * **为什么是独立的一页**:这个值历史上只出现在「声音克隆」的表单里(克隆先有了它),而转写和
 * 人声分离装依赖时读的是同一份 —— 想给转写换个镜像的人得去「声音克隆」里找。三个引擎一次拉
 * 2–3 GB 的 Python 依赖,国内直连 PyPI 常常慢到不可用,所以这是装任何本机引擎之前就该看得到的。
 *
 * 选中即保存:这里只有一个字段,再要求点一次「保存」只是多一步。
 */
export function InstallSourceSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const source = useQuery({ queryKey: ["install-source"], queryFn: getInstallSource });
  const save = useMutation({
    mutationFn: (value: string) => updateInstallSource(value),
    onSuccess: (next) => {
      qc.setQueryData(["install-source"], next);
      toast.success(t("saved"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const current = source.data?.pip_index || "pypi";
  const labels: Record<(typeof PRESETS)[number], string> = {
    pypi: t("voiceClonePipPypi"),
    tsinghua: t("voiceClonePipTsinghua"),
    aliyun: t("voiceClonePipAliyun"),
    tencent: t("voiceClonePipTencent"),
  };
  //: 自定义的 URL 不在预设里 —— 也要显示得出来,否则下拉会把它"纠正"成空。
  const options = [
    ...PRESETS.map((key) => ({ value: key, label: labels[key] })),
    ...(PRESETS.includes(current as (typeof PRESETS)[number]) ? [] : [{ value: current, label: current }]),
  ];

  return (
    <SettingsGroup title={t("installSourceTitle")} description={t("installSourceDesc")}>
      <SettingsRow label={t("voiceClonePipIndex")} description={t("voiceClonePipIndexHint")}>
        <OptionPicker
          ariaLabel={t("voiceClonePipIndex")}
          className={SETTINGS_FIELD_WIDTH}
          value={current}
          disabled={source.isLoading || save.isPending}
          onChange={(next) => save.mutate(next === "pypi" ? "" : next)}
          options={options}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
