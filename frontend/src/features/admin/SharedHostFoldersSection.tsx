import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Plus, X } from "lucide-react";
import { toast } from "sonner";

import { getSharedHostFolders, setSharedHostFolders } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  SettingsBlock,
  SettingsGroup,
  SettingsListBlock,
  SettingsListItem,
  SettingsRow,
  SETTINGS_FIELD_WIDTH,
} from "@/components/settings/settings-layout";

/**
 * 这台电脑上哪些文件夹共享给成员读。
 *
 * 本机文件是部署主人的私有资源(见 backend domain/host_files):管理员读哪里都行,其他成员在工作流里
 * 填本机路径、从本机导入素材时,只读得到这里列出来的文件夹。和开放注册一样是**这台部署**的决定,
 * 所以放在管理控制台,不在个人设置里。存的是后端展开过的真实路径,列表就照它显示。
 */
export function SharedHostFoldersSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const folders = useQuery({
    queryKey: ["shared-host-folders"],
    queryFn: getSharedHostFolders,
  });
  const [draft, setDraft] = React.useState("");
  // 正在取消共享的那一行 —— 只有它的按钮转圈,别的行照常可点。
  const [removing, setRemoving] = React.useState<string | null>(null);
  const save = useMutation({
    mutationFn: (next: string[]) => setSharedHostFolders(next),
    onSuccess: (data) => {
      qc.setQueryData(["shared-host-folders"], data);
      setDraft("");
    },
    onSettled: () => setRemoving(null),
    // 挡下来的那句话说清了是哪一条不对(不是绝对路径、没有这个文件夹、根目录)。
    onError: (error: Error) => toast.error(error.message),
  });
  const current = folders.data?.folders ?? [];
  const add = () => {
    const path = draft.trim();
    if (path) save.mutate([...current, path]);
  };

  return (
    <SettingsGroup title={t("deploySharedFoldersTitle")} description={t("deploySharedFoldersDesc")}>
      <SettingsRow
        label={t("deploySharedFoldersNew")}
        description={t("deploySharedFoldersNewDesc")}
        className="grid-cols-1 items-start"
      >
        <div className="flex w-full flex-wrap gap-1.5">
          <Input
            className={SETTINGS_FIELD_WIDTH}
            value={draft}
            placeholder={t("deploySharedFoldersPlaceholder")}
            aria-label={t("deploySharedFoldersNew")}
            onChange={(event) => setDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
          />
          <Button loading={save.isPending} disabled={!draft.trim()} onClick={add}>
            <Plus size={13} /> {t("deploySharedFoldersAdd")}
          </Button>
        </div>
      </SettingsRow>
      {current.length === 0 ? (
        <SettingsBlock>
          <p className="m-0 text-ui-xs text-muted-foreground">{t("deploySharedFoldersEmpty")}</p>
        </SettingsBlock>
      ) : (
        <SettingsListBlock>
          {current.map((folder) => (
            <SettingsListItem key={folder} className="flex items-center gap-2 text-ui-xs">
              <FolderOpen size={13} className="shrink-0 text-muted-foreground" />
              <code className="min-w-0 flex-1 truncate select-all" title={folder}>
                {folder}
              </code>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("deploySharedFoldersRemove")}
                title={t("deploySharedFoldersRemove")}
                loading={removing === folder}
                disabled={save.isPending}
                onClick={() => {
                  setRemoving(folder);
                  save.mutate(current.filter((one) => one !== folder));
                }}
              >
                <X />
              </Button>
            </SettingsListItem>
          ))}
        </SettingsListBlock>
      )}
    </SettingsGroup>
  );
}
