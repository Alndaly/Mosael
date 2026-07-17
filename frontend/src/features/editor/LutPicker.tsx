import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Trash2, Upload } from "lucide-react";

import { deleteLut, listLuts, uploadLut, type Lut } from "@/api/client";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useI18n } from "@/app/preferences";

const NONE = "__none__";

/** 3D LUT 选择 + 上传 + 删除。作用于 clip.effects.color.lut(存 LUT id)。
 *  预览无法用 CSS 表达 3D LUT,故仅导出生效 —— UI 明说,避免误解。 */
export function LutPicker({
  workspaceId,
  value,
  onChange,
}: {
  workspaceId: string;
  value: string | undefined;
  onChange: (lutId: string | undefined) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const fileRef = React.useRef<HTMLInputElement | null>(null);
  const luts = useQuery({
    queryKey: ["luts", workspaceId],
    queryFn: () => listLuts(workspaceId),
  });

  const upload = useMutation({
    mutationFn: (file: File) => uploadLut({ workspaceId, file }),
    onSuccess: (lut: Lut) => {
      void qc.invalidateQueries({ queryKey: ["luts", workspaceId] });
      onChange(lut.id); // 上传后即选中
      toast.success(t("lutUploaded"));
    },
    onError: (err: Error) => toast.error(err.message || t("lutUploadFailed")),
  });

  const remove = useMutation({
    mutationFn: (lutId: string) => deleteLut(lutId),
    onSuccess: (_data, lutId) => {
      void qc.invalidateQueries({ queryKey: ["luts", workspaceId] });
      if (value === lutId) onChange(undefined); // 删掉正在用的就清空引用
      toast.success(t("lutDeleted"));
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const items = luts.data ?? [];
  // 引用了一个已不存在的 LUT(被别处删掉):回退到"无"显示,但不擅自改数据。
  const selectValue = value && items.some((l) => l.id === value) ? value : NONE;

  return (
    <div className="lut-picker">
      <div className="lut-row">
        <Select
          value={selectValue}
          onValueChange={(next) => onChange(next === NONE ? undefined : next)}
        >
          <SelectTrigger className="lut-select" aria-label={t("gradeGroupLut")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>{t("lutNone")}</SelectItem>
            {items.map((lut) => (
              <SelectItem key={lut.id} value={lut.id}>
                {lut.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button
          type="button"
          className="grade-icon-btn"
          title={t("lutUpload")}
          aria-label={t("lutUpload")}
          disabled={upload.isPending}
          onClick={() => fileRef.current?.click()}
        >
          <Upload size={12} />
        </button>
        {selectValue !== NONE && (
          <button
            type="button"
            className="grade-icon-btn"
            title={t("lutDelete")}
            aria-label={t("lutDelete")}
            onClick={() => remove.mutate(selectValue)}
          >
            <Trash2 size={12} />
          </button>
        )}
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".cube"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) upload.mutate(file);
          event.target.value = ""; // 允许再次选同名文件
        }}
      />
      <p className="lut-hint">{t("lutHint")}</p>
    </div>
  );
}
