import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Trash2, Upload } from "lucide-react";

import { deleteLut, listLuts, uploadLut, type Lut } from "@/api/client";
import { OptionPicker } from "@/components/ui/option-picker";
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
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex min-w-0 items-center gap-1.5">
        {/* 调色预设是**攒出来**的:装几十个 .cube 很常见,超过阈值就换成可搜索的那一版。 */}
        <OptionPicker
          value={selectValue}
          onChange={(next) => onChange(next === NONE ? undefined : next)}
          options={[
            { value: NONE, label: t("lutNone") },
            ...items.map((lut) => ({ value: lut.id, label: lut.name })),
          ]}
          ariaLabel={t("gradeGroupLut")}
          className="min-w-0 flex-1"
        />
        <button
          type="button"
          className="inline-flex h-[22px] w-[22px] shrink-0 cursor-pointer items-center justify-center rounded-md border border-border bg-transparent text-muted-foreground enabled:hover:bg-muted enabled:hover:text-foreground disabled:cursor-default disabled:opacity-40"
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
            className="inline-flex h-[22px] w-[22px] shrink-0 cursor-pointer items-center justify-center rounded-md border border-border bg-transparent text-muted-foreground enabled:hover:bg-muted enabled:hover:text-foreground disabled:cursor-default disabled:opacity-40"
            title={t("lutDelete")}
            aria-label={t("lutDelete")}
            disabled={remove.isPending}
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
      <p className="m-0 text-ui-2xs leading-normal text-muted-foreground">{t("lutHint")}</p>
    </div>
  );
}
