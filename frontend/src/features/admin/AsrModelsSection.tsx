import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { downloadAsrModel, listAsrModels } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { pollWhileUnsettled } from "@/lib/pollWhileUnsettled";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";
import { ModelDownloadRow } from "./ModelDownloadRow";

/**
 * 管理 → 引擎 → 转写:预下载 funasr / whisperx 权重、装运行环境,展示进度、百分比、速度与剩余时间。
 * 转写首次会自动下载权重,这里给一个手动、可见的下载渠道。
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

  return (
    <AdminSection id="engine-transcribe" title={t("asrModelsTitle")} description={t("asrModelsDesc")}>
      <div className={ADMIN_CARD}>
        {models.data?.map((model) => (
          <ModelDownloadRow
            key={model.id}
            model={model}
            // 引擎族是一个 id(funasr / whisperx),照原样作小字 —— 不再是描边的大写小标。
            meta={model.engine}
            noRuntimeText={t("asrModelNoRuntime")}
            // 只看这一行自己在不在下 —— 每个引擎有自己的 venv,同时装不会互相弄坏。
            busy={(download.isPending && download.variables === model.id) || model.status === "downloading"}
            onDownload={() => download.mutate(model.id)}
          />
        ))}
        {models.isLoading && <AdminRow label={t("connecting")} />}
      </div>
    </AdminSection>
  );
}
