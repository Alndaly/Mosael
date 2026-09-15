import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Profile = components["schemas"]["GenerationCapabilityProfileOut"];

/**
 * 这条连接下的**自定义参数组**。
 *
 * **为什么在这里**:内置目录装的是我们查证过的东西,而中转端点的组合装不完 —— 同一个 gemini
 * 经两家中转,一家支持尺寸和多张、另一家只支持尺寸。指向内置那份会过度承诺:界面摆出一个
 * 「张数」旋钮,发出去被端点拒掉。这是把只有你知道的那份写下来的地方。
 *
 * **它不是"我们查证过的事实"**,是你的断言。所以这一节明说了这一点 —— 填错了不会当场报错,
 * 而是等到生成请求被供应商拒掉。保存时能拦的只有形状(sizes 得是一串文字、上限得是正整数),
 * 拦不住"这个端点真的支持 4 张吗"。
 */
export function GenerationProfilesSection({ profileId, kind }: { profileId: string; kind: "image" | "video" }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<Profile | "new" | null>(null);

  const list = useQuery({
    queryKey: ["generation-profiles", profileId, kind],
    queryFn: () => api<Profile[]>(`/api/settings/providers/${profileId}/generation-profiles?kind=${kind}`),
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
    <div className="grid gap-1.5">
      <button
        type="button"
        className="flex w-full cursor-pointer items-center justify-between gap-2 border-0 bg-transparent p-0 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="text-ui-sm font-medium text-muted-foreground">
          {t("generationProfiles")}
          {rows.length > 0 && <span className="ml-1.5 font-normal text-faint">{rows.length}</span>}
        </span>
        <ChevronDown size={13} className={cn("shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
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
      )}

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
    </div>
  );
}

/**
 * 新建 / 编辑一份参数组。
 *
 * **正文是 JSON。** 三十几个字段、彼此有依赖(default_size 要在 sizes 里)、形状各不相同
 * (一串文字 / 一组「名字→上限」/ 若干组互斥角色)——给每一种做一个控件,是在给一件本来就该
 * 照抄的事发明一套界面。而这份内容的来源通常就是供应商文档里那段 JSON。
 *
 * 代价是要看得懂 JSON;补偿是**保存时逐项校验并点名说错在哪个键**,而不是"格式不对"。
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
  const [text, setText] = React.useState(() =>
    JSON.stringify(row?.capabilities ?? { parameter_keys: ["size"], sizes: ["1024x1024"], default_size: "1024x1024" }, null, 2),
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
          <Button
            loading={save.isPending}
            onClick={() => {
              let parsed: unknown;
              try {
                parsed = JSON.parse(text);
              } catch {
                //: JSON 本身坏掉时不发请求 —— 那一句报错该在这里出,而不是绕一圈从服务端回来。
                setError(t("generationProfilesBadJson"));
                return;
              }
              setError("");
              save.mutate({ name, capabilities: parsed });
            }}
          >
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
        <label className="grid gap-1 text-ui-sm font-medium text-foreground">
          {t("generationProfilesBody")}
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={14}
            spellCheck={false}
            className="w-full resize-y rounded-md border border-border bg-panel px-2.5 py-2 font-mono text-ui-xs leading-[1.6] text-foreground outline-none focus:border-primary"
          />
        </label>
        {error && <p className="m-0 text-ui-xs leading-[1.45] text-destructive">{error}</p>}
        <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("generationProfilesDisclaimer")}</p>
      </div>
    </ModalShell>
  );
}
