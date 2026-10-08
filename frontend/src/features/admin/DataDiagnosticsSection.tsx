import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, FileOutput, Loader2, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { useI18n } from "@/app/preferences";
import { api, getAuthToken, isCustomServer } from "@/api/client";
import { Button } from "@/components/ui/button";
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
import { OptionPicker } from "@/components/ui/option-picker";
import { ADMIN_CARD, AdminRow, AdminSection } from "./adminLayout";

type JobRetention = { days: number | null };
const FOREVER = "forever";
//: 能选的几档(天);后端 domain/deployment.JOB_RETENTION_CHOICES 照同一组校验,别的数回 422。
const RETENTION_DAYS = [90, 180, 365];

/**
 * 任务记录保留多久(ADR 0050 D29):结束超过这么多天的任务由后台的保留清理删掉;被定时任务运行、生成记录、发布记录指着的
 * 和记过用量的不删。任务中心的「清空已结束」不删东西,只从各人的面板上拿掉 —— 真删只在这里定。
 */
function JobRetentionRow() {
  const t = useI18n();
  const qc = useQueryClient();
  const retention = useQuery({ queryKey: ["admin", "job-retention"], queryFn: () => api<JobRetention>("/api/admin/job-retention") });
  const save = useMutation({
    mutationFn: (days: number | null) =>
      api<JobRetention>("/api/admin/job-retention", { method: "PUT", body: JSON.stringify({ days }) }),
    onSuccess: (saved) => qc.setQueryData(["admin", "job-retention"], saved),
    onError: (error: Error) => toast.error(error.message),
  });
  const value = retention.data ? (retention.data.days === null ? FOREVER : String(retention.data.days)) : "";
  const options = [
    ...RETENTION_DAYS.map((days) => ({ value: String(days), label: t("jobRetentionDays").replace("{n}", String(days)) })),
    { value: FOREVER, label: t("jobRetentionForever") },
  ];
  return (
    <AdminRow label={t("jobRetentionLabel")} description={t("jobRetentionDesc")}>
      <OptionPicker
        className="w-40"
        ariaLabel={t("jobRetentionLabel")}
        value={value}
        options={options}
        disabled={!retention.data || save.isPending}
        onChange={(next) => save.mutate(next === FOREVER ? null : Number(next))}
      />
    </AdminRow>
  );
}

/**
 * 数据与诊断:备份、恢复、诊断包 —— 动的是整台部署的数据库和日志,不是某个人的东西。
 *
 * 所以在管理页:备份和恢复的接口只给部署管理员(routes/settings/data.py),诊断包里是整台后端的日志。
 */
export function DataDiagnosticsSection() {
  const t = useI18n();
  const [exporting, setExporting] = React.useState(false);
  const [backingUp, setBackingUp] = React.useState(false);
  const [restoring, setRestoring] = React.useState(false);
  const [pendingRestore, setPendingRestore] = React.useState<File | null>(null);
  const restoreInput = React.useRef<HTMLInputElement>(null);
  const usesLocalBackend = !isCustomServer();
  const exportDiagnostics = window.mosaelDesktop?.data?.exportDiagnostics;
  const createBackup = usesLocalBackend ? window.mosaelDesktop?.data?.createBackup : undefined;
  const applyRestore = usesLocalBackend ? window.mosaelDesktop?.data?.applyRestore : undefined;
  const unavailableLabel = window.mosaelDesktop && !usesLocalBackend
    ? t("dataDiagnosticsLocalOnly")
    : t("dataDiagnosticsDesktopOnly");

  return (
    <AdminSection id="data" title={t("dataDiagnosticsTitle")} description={t("dataDiagnosticsDesc")}>
      <div className={ADMIN_CARD}>
        <JobRetentionRow />
        <AdminRow label={t("dataDiagnosticsBundle")} description={t("dataDiagnosticsBundleDesc")}>
          {exportDiagnostics ? (
            <Button
              size="sm"
              variant="outline"
              disabled={exporting}
              onClick={async () => {
                setExporting(true);
                try {
                  const result = await exportDiagnostics();
                  if (result.status === "saved") toast.success(t("dataDiagnosticsSaved"));
                } catch {
                  toast.error(t("dataDiagnosticsFailed"));
                } finally {
                  setExporting(false);
                }
              }}
            >
              {exporting ? <Loader2 size={13} className="animate-mosael-spin" /> : <FileOutput size={13} />}
              {t("dataDiagnosticsExport")}
            </Button>
          ) : (
            <span className="text-ui-sm text-muted-foreground">{unavailableLabel}</span>
          )}
        </AdminRow>
        <AdminRow label={t("dataDiagnosticsBackup")} description={t("dataDiagnosticsBackupDesc")}>
          {createBackup ? (
            <Button
              size="sm"
              variant="outline"
              disabled={backingUp}
              onClick={async () => {
                const token = getAuthToken();
                if (!token) {
                  toast.error(t("dataDiagnosticsBackupFailed"));
                  return;
                }
                setBackingUp(true);
                try {
                  const result = await createBackup(token);
                  if (result.status === "saved") toast.success(t("dataDiagnosticsBackupSaved"));
                } catch {
                  toast.error(t("dataDiagnosticsBackupFailed"));
                } finally {
                  setBackingUp(false);
                }
              }}
            >
              {backingUp ? <Loader2 size={13} className="animate-mosael-spin" /> : <Archive size={13} />}
              {t("dataDiagnosticsBackupCreate")}
            </Button>
          ) : (
            <span className="text-ui-sm text-muted-foreground">{unavailableLabel}</span>
          )}
        </AdminRow>
        <AdminRow label={t("dataDiagnosticsRestore")} description={t("dataDiagnosticsRestoreDesc")}>
          {applyRestore ? (
            <>
              <input
                ref={restoreInput}
                className="hidden"
                type="file"
                accept=".mosael-backup,application/zip"
                aria-label={t("dataDiagnosticsRestoreFile")}
                onChange={(event) => {
                  const selected = event.currentTarget.files?.[0] ?? null;
                  event.currentTarget.value = "";
                  if (selected) setPendingRestore(selected);
                }}
              />
              <Button
                size="sm"
                variant="outline"
                disabled={restoring}
                onClick={() => restoreInput.current?.click()}
              >
                {restoring ? <Loader2 size={13} className="animate-mosael-spin" /> : <RotateCcw size={13} />}
                {t("dataDiagnosticsRestoreChoose")}
              </Button>
            </>
          ) : (
            <span className="text-ui-sm text-muted-foreground">{unavailableLabel}</span>
          )}
        </AdminRow>
      </div>
      <AlertDialog open={pendingRestore !== null} onOpenChange={(open) => !open && setPendingRestore(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("dataDiagnosticsRestoreConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("dataDiagnosticsRestoreConfirmDesc").replace("{name}", pendingRestore?.name ?? "")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={restoring}>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={restoring}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={async () => {
                if (!pendingRestore || !applyRestore) return;
                setRestoring(true);
                try {
                  const form = new FormData();
                  form.append("file", pendingRestore);
                  const staged = await api<{ stage_id: string }>("/api/settings/data/restore/stage", {
                    method: "POST",
                    body: form,
                  });
                  await applyRestore(staged.stage_id);
                } catch {
                  setRestoring(false);
                  toast.error(t("dataDiagnosticsRestoreFailed"));
                }
              }}
            >
              {t("dataDiagnosticsRestoreConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AdminSection>
  );
}
