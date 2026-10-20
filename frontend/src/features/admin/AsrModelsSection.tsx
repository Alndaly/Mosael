import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { toast } from "sonner";

import { downloadAsrModel, listAsrModels, setDefaultAsrModel } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { ADMIN_CARD, AdminRow, AdminRowState, AdminSection } from "./adminLayout";
import { AdminDefaultLine, hasDefaultChoice } from "./defaultRow";
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
    //: 接口拒了(没安装 / 不认识的 id)要把原因原样说出来 —— 一颗点了没反应的按钮等于坏了。
    onError: (error: Error) => toast.error(error.message),
  });

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
          位置和别处一样:节说明之后、模型列表之前。 */}
      <AdminDefaultLine
        label={t("asrModelIsDefault")}
        optionCount={models.data?.length}
        current={models.data?.find((model) => model.is_default)?.label ?? t("asrDefaultAuto")}
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
            // 已默认 = 一枚**状态**,不是一颗按钮:它不能再点(再点一次也还是它)。
            // 没安装的卡上没有这一格 —— 设一份没装的,"默认"只是一句空话(后端也会拒,见 set_default_model)。
            // 整个"默认"只在这一节有 ≥2 个候选时才摆(见 defaultRow);只有一种实现时它没有意义。
            extra={
              hasDefaultChoice(models.data?.length) ? (
                model.is_default ? (
                  <AdminRowState tone="success" icon={<Star size={13} />}>
                    {t("asrModelIsDefault")}
                  </AdminRowState>
                ) : model.status === "installed" ? (
                  <Button
                    size="sm"
                    variant="outline"
                    loading={setDefault.isPending && setDefault.variables === model.id}
                    disabled={setDefault.isPending && setDefault.variables === model.id}
                    onClick={() => setDefault.mutate(model.id)}
                  >
                    {t("asrModelSetDefault")}
                  </Button>
                ) : null
              ) : null
            }
            onDownload={() => download.mutate(model.id)}
          />
        ))}
        {models.isLoading && <AdminRow label={t("connecting")} />}
      </div>
    </AdminSection>
  );
}
