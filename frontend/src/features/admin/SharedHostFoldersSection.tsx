import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { getSharedHostFolders, setSharedHostFolders } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { isImeKeystroke } from "@/lib/shortcuts";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

const QUERY_KEY = ["shared-host-folders"] as const;

/**
 * 这台电脑上哪些文件夹共享给成员读。
 *
 * 本机文件是部署主人的私有资源(见 backend domain/host_files):管理员读哪里都行,其他成员在工作流里
 * 填本机路径、从本机导入素材时,只读得到这里列出来的文件夹。和开放注册一样是**这台部署**的决定,
 * 所以放在管理控制台,不在个人设置里。存的是后端展开过的真实路径,列表就照它显示。
 *
 * 加一条 / 去一条都是**整份清单** PUT 回去 —— 后端负责校验与展开,这里不自己拼路径。
 */
export function SharedHostFoldersSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const folders = useQuery({ queryKey: QUERY_KEY, queryFn: getSharedHostFolders });
  const current = folders.data?.folders ?? [];
  const [adding, setAdding] = React.useState(false);
  // 正在取消共享的那一行 —— 只有它的按钮转圈,别的行照常可点。
  const [removing, setRemoving] = React.useState<string | null>(null);
  const remove = useMutation({
    mutationFn: (next: string[]) => setSharedHostFolders(next),
    onSuccess: (data) => qc.setQueryData(QUERY_KEY, data),
    onSettled: () => setRemoving(null),
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <AdminSection
      id="shared-folders"
      title={t("deploySharedFoldersTitle")}
      description={t("deploySharedFoldersDesc")}
      actions={
        <Button size="sm" variant="outline" disabled={!folders.isSuccess} onClick={() => setAdding(true)}>
          <Plus size={13} /> {t("deploySharedFoldersNew")}
        </Button>
      }
    >
      <div className={ADMIN_CARD}>
        {folders.isPending ? (
          <div className="px-4 py-3">
            <Skeleton className="h-8 w-full" />
          </div>
        ) : current.length === 0 ? (
          <EmptyState size="compact" icon={<FolderOpen size={15} />} title={t("deploySharedFoldersEmpty")} body={t("deploySharedFoldersEmptyBody")} />
        ) : (
          current.map((folder) => (
            <AdminRow
              key={folder}
              leading={<FolderOpen size={15} className="shrink-0 text-muted-foreground" />}
              label={
                <code className="timecode select-all font-normal" title={folder}>
                  {folder}
                </code>
              }
            >
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("deploySharedFoldersRemove")}
                title={t("deploySharedFoldersRemove")}
                loading={removing === folder}
                disabled={remove.isPending}
                onClick={() => {
                  setRemoving(folder);
                  remove.mutate(current.filter((one) => one !== folder));
                }}
              >
                <X />
              </Button>
            </AdminRow>
          ))
        )}
      </div>
      <AddFolderDialog open={adding} current={current} onClose={() => setAdding(false)} />
    </AdminSection>
  );
}

/**
 * 加一个文件夹。后端挡下来的那句话(不是绝对路径、没有这个文件夹、根目录)**留在弹窗里**,
 * 贴着那个输入框 —— 他要改的正是这一格,弹个 toast 再让它消失只会让人去猜刚才说了什么。
 */
function AddFolderDialog({ open, current, onClose }: { open: boolean; current: string[]; onClose: () => void }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [draft, setDraft] = React.useState("");
  const save = useMutation({
    mutationFn: (next: string[]) => setSharedHostFolders(next),
    onSuccess: (data) => {
      qc.setQueryData(QUERY_KEY, data);
      onClose();
    },
  });
  React.useEffect(() => {
    if (open) {
      setDraft("");
      save.reset();
    }
    // save.reset 每次渲染都是新引用;只在打开的那一下清空。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  const path = draft.trim();
  const submit = () => {
    if (path && !save.isPending) save.mutate([...current, path]);
  };
  const errorId = React.useId();

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && !save.isPending && onClose()}
      title={t("deploySharedFoldersNew")}
      className="w-[440px]"
      footer={
        <>
          <Button variant="outline" disabled={save.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button loading={save.isPending} disabled={!path} onClick={submit}>
            {t("deploySharedFoldersAdd")}
          </Button>
        </>
      }
    >
      <label className={DIALOG_FIELD}>
        <span>{t("deploySharedFoldersPath")}</span>
        <Input
          autoFocus
          value={draft}
          placeholder={t("deploySharedFoldersPlaceholder")}
          aria-invalid={save.isError || undefined}
          aria-describedby={save.isError ? errorId : undefined}
          onChange={(event) => {
            setDraft(event.currentTarget.value);
            if (save.isError) save.reset();
          }}
          onKeyDown={(event) => {
            if (isImeKeystroke(event)) return;
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
        />
        {save.isError ? (
          <small id={errorId} role="alert" className="!text-destructive">
            {save.error.message}
          </small>
        ) : (
          <small>{t("deploySharedFoldersNewDesc")}</small>
        )}
      </label>
    </ModalShell>
  );
}
