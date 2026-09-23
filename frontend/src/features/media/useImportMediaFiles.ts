import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { importAsset } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { assetKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";

/**
 * 把一批本机文件导入成素材。素材页的「导入」按钮、拖进素材页、剪辑页素材池的导入都走这一个。
 *
 * 此前按钮只收第一个文件,拖放才收一批 —— 同一件事两种能力,用户在选择框里多选了十个,
 * 进来的只有一个,而且什么也不说。
 *
 * **逐个传,不并发**:一次十个视频,并发会把带宽和后端的转码队列同时打满,用户看到的是
 * 十个都卡着不动。**一个失败不拦后面的**:第三个格式不支持,不该让后面七个也不进来;
 * 最后一并说清进来几个、哪几个没进来、为什么。
 */
export function useImportMediaFiles({ workspaceId, projectId }: { workspaceId: string; projectId?: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (files: File[]) => {
      let imported = 0;
      const failed: Array<{ name: string; reason: string }> = [];
      for (const file of files) {
        try {
          await importAsset({ workspaceId, projectId, file });
          imported += 1;
        } catch (error) {
          failed.push({ name: file.name, reason: errorText(error) });
        }
      }
      return { imported, failed };
    },
    onSuccess: ({ imported, failed }) => {
      void qc.invalidateQueries({ queryKey: assetKeys.all(workspaceId) });
      if (failed.length === 0) {
        toast.success(t("mediaDropped").replace("{n}", String(imported)));
        return;
      }
      const first = failed[0];
      toast.error(
        t("mediaImportPartial")
          .replace("{n}", String(imported))
          .replace("{m}", String(failed.length))
          .replace("{name}", first.name)
          .replace("{reason}", first.reason),
      );
    },
  });
}
