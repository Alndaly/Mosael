import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { saveDocumentAsNote } from "@/api/domains/documents";
import { openNote } from "@/lib/deepLink";
import { assetKeys, noteKeys } from "@/api/queryKeys";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";

/** 「转为笔记」(ADR 0031):素材库的右键 / ⋯ 菜单和文档详情共用这一个。做成了给一个「打开笔记」。 */
export function useSaveDocumentAsNote() {
  const t = useI18n();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (assetId: string) => saveDocumentAsNote(assetId),
    onSuccess: (made) => {
      void qc.invalidateQueries({ queryKey: noteKeys.everywhere() });
      //: 插图这时进了素材库。
      void qc.invalidateQueries({ queryKey: assetKeys.everywhere() });
      toast.success(t("docSavedAsNote").replace("{title}", made.title), {
        action: { label: t("docOpenNote"), onClick: () => openNote(made.note_id) },
      });
    },
    onError: (error) => toast.error(errorText(error)),
  });
}
