import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { downloadAsrModel, listAsrModels, setDefaultAsrModel } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";
import { AdminDefaultMarker, AdminDefaultSelect, hasDefaultChoice } from "./defaultRow";
import { ModelDownloadRow } from "./ModelDownloadRow";

/**
 * 管理 → 引擎 → 转写:预下载 funasr / sherpa-onnx / whisperx 权重、装运行环境,展示进度、百分比、速度与剩余时间,
 * 并把其中**已经装在盘上**的那一份设成这台机器的默认模型。
 * 转写首次会自动下载权重,这里给一个手动、可见的下载渠道。
 *
 * 默认是**这台机器**的设定(和「默认克隆引擎」同一类):只有部署管理员能改,和下载同一道门
 * (routes/asr.set_default_asr_model)。它是两层里的**全局默认**那一层 ——「语音对话 → 说话输入用哪一家」
 * 是按用途的覆盖,留空就回到这里(有效值只在 domain/asr.resolve_asr_model 里算)。
 *
 * 在管理页:往这台机器上下模型、装依赖只给部署管理员(routes/asr.download_asr_model)。
 */
export function AsrModelsSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const models = useQuery({
    queryKey: ["asr-models"],
    queryFn: listAsrModels,
    refetchInterval: (query) => pollWhileUnsettled(query.state.data),
  });
  const download = useMutation({
    mutationFn: (id: string) => downloadAsrModel(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["asr-models"] }),
    onError: (error: Error) => toast.error(error.message),
  });
  const setDefault = useMutation({
    mutationFn: (id: string) => setDefaultAsrModel(id),
    //: **从后端重新读整张列表**,不是只把本地这一行改成默认:默认只有一个,原来那一个也得跟着改口。
    //: (后端的回包就是改完之后的那一行,但其余行只有再问一次才知道。)
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["asr-models"] }),
    //: 接口拒了(没安装 / 不认识的 id)要把原因原样说出来 —— 点了没反应的控件等于坏了。
    //: 界面上未安装的选项已经禁用(后端仍会回 409,见 routes/asr.set_default_asr_model),这里兜住那一路。
    onError: (error: Error) => toast.error(error.message),
  });

  const options = models.data?.map((model) => ({
    id: model.id,
    label: model.label,
    //: 设默认看的是**权重在不在盘上**(status),不是运行环境探没探完 —— 后者只是还没答。
    installed: model.status === "installed",
  }));
  const defaultModel = models.data?.find((model) => model.is_default);
  const canSetDefault = hasDefaultChoice(models.data?.length);

  return (
    <AdminSection
      id="engine-transcribe"
      title={t("asrModelsTitle")}
      description={
        <>
          {t("asrModelsDesc")} {t("asrDefaultHint")}
        </>
      }
    >
      {/* 默认只在这一节有**多个**可选模型时才存在;只有一种时说清为什么没有默认可设(见 defaultRow)。
          整个「设默认」只有这一处:说明之后、模型列表之前;列表行不再有按钮。 */}
      <AdminDefaultSelect
        label={t("asrModelIsDefault")}
        options={options}
        value={defaultModel?.id}
        placeholder={t("asrDefaultAuto")}
        disabled={setDefault.isPending}
        onChange={(id) => setDefault.mutate(id)}
      />
      <div className={ADMIN_CARD}>
        {models.data?.map((model) => (
          <ModelDownloadRow
            key={model.id}
            model={model}
            // 引擎族是一个 id(funasr / sherpa-onnx / whisperx),照原样作小字 —— 不再是描边的大写小标。
            meta={model.engine}
            noRuntimeText={t("asrModelNoRuntime")}
            // 只看这一行自己在不在下 —— 每个引擎有自己的 venv,同时装不会互相弄坏。
            busy={(download.isPending && download.variables === model.id) || model.status === "downloading"}
            busyReason={t("ttsThisDownloading")}
            // 已默认只是名字右边**一枚 badge**,不是按钮、也不占右边状态槽:改默认在节顶那个选择器里
            // (唯一可写处)。整个"默认"只在这一节有 ≥2 个候选时才摆(见 defaultRow);只有一种实现时它没有意义。
            tags={canSetDefault && model.is_default ? <AdminDefaultMarker /> : null}
            onDownload={() => download.mutate(model.id)}
          />
        ))}
        {models.isLoading && <AdminRow label={t("connecting")} />}
      </div>
    </AdminSection>
  );
}
