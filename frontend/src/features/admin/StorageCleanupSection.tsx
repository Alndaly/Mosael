import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { deleteStorageOrphans, storageOrphansQuery, type StorageOrphan } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { formatBytes } from "@/lib/bytes";
import { ADMIN_CARD, AdminSection } from "./adminLayout";

const REASON_LABEL: Record<string, MessageKey> = {
  workspace_gone: "storageOrphanWorkspaceGone",
  row_gone: "storageOrphanRowGone",
  avatar_unused: "storageOrphanAvatarUnused",
};

/**
 * 存储清理:数据目录里没人认领的文件(工作区 / 素材 / 音色 / LUT / 字体已经删了、文件还在的,没人用的头像)。
 *
 * **只列出来,勾选、确认之后才删**(后端 domain/storage_cleanup):判据是「此刻库里没有对应的行」,恢复到一半的备份、
 * 换过的数据目录都可能让一份有用的文件看起来像孤儿 —— 所以不自动删。刚开始导入的(一小时内动过的)不算。
 */
export function StorageCleanupSection() {
  const t = useI18n();
  const qc = useQueryClient();
  const orphans = useQuery(storageOrphansQuery());
  const [picked, setPicked] = React.useState<Set<string>>(new Set());
  const [confirming, setConfirming] = React.useState(false);
  const items = orphans.data?.items ?? [];
  const chosen = items.filter((one) => picked.has(one.key));
  const chosenBytes = chosen.reduce((sum, one) => sum + one.bytes, 0);

  const remove = useMutation({
    mutationFn: (keys: string[]) => deleteStorageOrphans(keys),
    onSuccess: (result) => {
      setPicked(new Set());
      toast.success(t("storageOrphansDeleted").replace("{n}", String(result.deleted.length)));
      if (result.skipped.length) toast.message(t("storageOrphansSkipped").replace("{n}", String(result.skipped.length)));
      void qc.invalidateQueries({ queryKey: storageOrphansQuery().queryKey });
    },
    onError: (error) => toast.error(t("storageOrphansDeleteFailed"), { description: errorText(error) }),
  });

  const toggle = (one: StorageOrphan, on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      if (on) next.add(one.key);
      else next.delete(one.key);
      return next;
    });

  return (
    <AdminSection id="storage" title={t("storageCleanupTitle")} description={t("storageCleanupDesc")}>
      <div className={ADMIN_CARD} data-storage-cleanup="">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <span className="text-ui-sm text-muted-foreground">
            {orphans.isLoading
              ? t("storageOrphansLoading")
              : items.length
                ? t("storageOrphansSummary").replace("{n}", String(items.length)).replace("{size}", formatBytes(orphans.data?.total_bytes ?? 0))
                : t("storageOrphansNone")}
          </span>
          <div className="flex items-center gap-1.5">
            <Button size="sm" variant="ghost" onClick={() => void orphans.refetch()} loading={orphans.isFetching}>
              <RefreshCw size={13} />
              {t("storageOrphansRescan")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!chosen.length || remove.isPending}
              loading={remove.isPending}
              onClick={() => setConfirming(true)}
            >
              <Trash2 size={13} />
              {t("storageOrphansDelete").replace("{n}", String(chosen.length))}
            </Button>
          </div>
        </div>
        {items.length ? (
          <ul className="divide-y divide-divider border-t border-divider">
            {items.map((one) => (
              <li key={one.key} className="flex items-center gap-3 px-4 py-2" data-storage-orphan={one.key}>
                <Checkbox
                  checked={picked.has(one.key)}
                  onCheckedChange={(on) => toggle(one, on === true)}
                  aria-label={one.key}
                />
                <HardDrive size={14} className="shrink-0 text-muted-foreground" aria-hidden />
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="truncate font-mono text-ui-xs text-foreground">{one.key}</span>
                  <span className="text-ui-xs text-muted-foreground">
                    {t(REASON_LABEL[one.reason] ?? "storageOrphanRowGone")} · {formatBytes(one.bytes)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("storageOrphansConfirmTitle").replace("{n}", String(chosen.length))}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("storageOrphansConfirmBody").replace("{size}", formatBytes(chosenBytes))}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => remove.mutate(chosen.map((one) => one.key))}>
              {t("storageOrphansConfirmAction")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AdminSection>
  );
}
