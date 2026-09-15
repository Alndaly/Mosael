import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { CapabilityProfileForm } from "./GenerationProfileForm";

type Profile = components["schemas"]["GenerationCapabilityProfileOut"];

/**
 * 这条连接下的**自定义参数组**管理(对话框)。
 *
 * **为什么在这里**:内置目录装的是我们查证过的东西,而中转端点的组合装不完 —— 同一个 gemini
 * 经两家中转,一家支持尺寸和多张、另一家只支持尺寸。指向内置那份会过度承诺:界面摆出一个
 * 「张数」旋钮,发出去被端点拒掉。这是把只有你知道的那份写下来的地方。
 *
 * **入口在连接行的溢出菜单里**,不挂在模型列表底下 —— 折叠的一节沉在列表最底,要用它的人
 * 根本找不到(见 settings 重构)。它不是"我们查证过的事实",是你的断言:填错了不会当场报错,
 * 而是等到生成请求被供应商拒掉;保存时能拦的只有形状(sizes 得是一串文字、上限得是正整数),
 * 拦不住"这个端点真的支持 4 张吗"。
 */
export function GenerationProfilesDialog({
  profileId,
  kind,
  open,
  onOpenChange,
}: {
  profileId: string;
  kind: "image" | "video";
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState<Profile | "new" | null>(null);

  const list = useQuery({
    queryKey: ["generation-profiles", profileId, kind],
    queryFn: () => api<Profile[]>(`/api/settings/providers/${profileId}/generation-profiles?kind=${kind}`),
    enabled: open,
  });
  const rows = list.data ?? [];

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["generation-profiles", profileId, kind] });
    //: 选择器和生成页都要跟着变 —— 刚建好的那份要能马上选到,刚删掉的要马上从下拉里消失。
    void qc.invalidateQueries({ queryKey: ["generation-capability-refs"] });
    void qc.invalidateQueries({ queryKey: ["capability-models"] });
    void qc.invalidateQueries({ queryKey: ["provider-models", profileId] });
  };

  const remove = useMutation({
    mutationFn: (id: string) =>
      api<void>(`/api/settings/providers/${profileId}/generation-profiles/${id}`, { method: "DELETE" }),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={t("generationProfiles")}>
      <div className="grid gap-1.5">
        <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("generationProfilesHint")}</p>
        {rows.map((row) => (
          <div key={row.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md border border-border bg-panel px-3 py-2">
            <div className="grid min-w-0 gap-0.5">
              <span className="truncate text-ui-sm font-medium text-foreground">{row.name}</span>
              {/* 参数名直接列出来 —— 一份参数组"是什么"就是这几项,收在弹窗里等于要点开才知道。 */}
              <span className="truncate text-ui-2xs text-muted-foreground">
                {(row.capabilities?.parameter_keys as string[] | undefined)?.join(" · ") || t("modelGenerationRefNoParams")}
              </span>
            </div>
            <span className="flex shrink-0 items-center gap-0.5">
              <Button variant="ghost" size="icon-xs" aria-label={t("editAction")} onClick={() => setEditing(row)}>
                <Pencil size={13} />
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={t("delete")}
                loading={remove.isPending}
                onClick={() => remove.mutate(row.id)}
              >
                <Trash2 size={13} />
              </Button>
            </span>
          </div>
        ))}
        <Button variant="outline" size="sm" className="justify-self-start" onClick={() => setEditing("new")}>
          <Plus size={13} /> {t("generationProfilesAdd")}
        </Button>
      </div>

      {editing && (
        <ProfileEditor
          profileId={profileId}
          kind={kind}
          row={editing === "new" ? null : editing}
          onDone={() => {
            setEditing(null);
            invalidate();
          }}
        />
      )}
    </ModalShell>
  );
}

/**
 * 新建 / 编辑一份参数组 —— **语义化表单,不写 JSON**。
 *
 * 表单结构由后端 schema 端点驱动(见 GenerationProfileForm):三十几个字段、彼此有依赖
 * (default_size 要在 sizes 里)、形状各不相同 —— 每一种都有对应控件。保存时后端仍逐项
 * 校验并点名说错在哪个键(形状是后端的事,表单只负责让人少填错)。
 */
function ProfileEditor({
  profileId,
  kind,
  row,
  onDone,
}: {
  profileId: string;
  kind: "image" | "video";
  row: Profile | null;
  onDone: () => void;
}) {
  const t = useI18n();
  const [name, setName] = React.useState(row?.name ?? "");
  const [descriptor, setDescriptor] = React.useState<Record<string, unknown>>(() =>
    row?.capabilities
      ? { ...row.capabilities }
      : { parameter_keys: ["size"], sizes: ["1024x1024"], default_size: "1024x1024" },
  );
  const [error, setError] = React.useState("");

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      row
        ? api<Profile>(`/api/settings/providers/${profileId}/generation-profiles/${row.id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          })
        : api<Profile>(`/api/settings/providers/${profileId}/generation-profiles`, {
            method: "POST",
            body: JSON.stringify({ ...body, kind }),
          }),
    onSuccess: onDone,
    //: 后端的报错已经是可以直接给人看的话(点名了是哪个键),原样显示,别包一层"保存失败"。
    onError: (err: Error) => setError(err.message),
  });

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && onDone()}
      title={row ? t("generationProfilesEdit") : t("generationProfilesAdd")}
      footer={
        <>
          <Button variant="outline" onClick={onDone}>{t("cancel")}</Button>
          <Button loading={save.isPending} onClick={() => save.mutate({ name, capabilities: descriptor })}>
            {t("save")}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <label className="grid gap-1 text-ui-sm font-medium text-foreground">
          {t("generationProfilesName")}
          <Input value={name} onChange={(event) => setName(event.target.value)} className="bg-panel" />
        </label>
        <CapabilityProfileForm value={descriptor} onChange={setDescriptor} />
        {error && <p className="m-0 text-ui-xs leading-[1.45] text-destructive">{error}</p>}
        <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("generationProfilesDisclaimer")}</p>
      </div>
    </ModalShell>
  );
}
