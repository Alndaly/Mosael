import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { importAsset } from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { importEach, importFailureText } from "@/lib/importEach";

/**
 * 把一批本机文件导入成素材。素材页的「导入」按钮、拖进素材页、剪辑页素材池的导入都走这一个。
 *
 * 此前按钮只收第一个文件,拖放才收一批 —— 同一件事两种能力,用户在选择框里多选了十个,
 * 进来的只有一个,而且什么也不说。逐个传、一个失败不拦后面的,规矩见 lib/importEach。
 */
export function useImportMediaFiles({ workspaceId, projectId }: { workspaceId: string; projectId?: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) => importEach(files, (file) => importAsset({ workspaceId, projectId, file })),
    onSuccess: ({ imported, failed }) => {
      void qc.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      const partial = importFailureText(t, imported.length, failed);
      if (partial) toast.error(partial);
      else toast.success(t("mediaDropped").replace("{n}", String(imported.length)));
    },
  });
}
