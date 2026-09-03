import React from "react";
import { Archive, FileDown, Loader2, RotateCcw } from "lucide-react";
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
import { SettingsGroup, SettingsRow, SettingsSectionStack } from "@/features/settings/ui";

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
    <SettingsSectionStack>
      <SettingsGroup title={t("dataDiagnosticsTitle")} description={t("dataDiagnosticsDesc")}>
        <SettingsRow label={t("dataDiagnosticsBundle")} description={t("dataDiagnosticsBundleDesc")}>
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
              {exporting ? <Loader2 size={13} className="animate-mosael-spin" /> : <FileDown size={13} />}
              {t("dataDiagnosticsExport")}
            </Button>
          ) : (
            <span className="text-ui-sm text-muted-foreground">{unavailableLabel}</span>
          )}
        </SettingsRow>
        <SettingsRow label={t("dataDiagnosticsBackup")} description={t("dataDiagnosticsBackupDesc")}>
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
        </SettingsRow>
        <SettingsRow label={t("dataDiagnosticsRestore")} description={t("dataDiagnosticsRestoreDesc")}>
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
        </SettingsRow>
      </SettingsGroup>
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
    </SettingsSectionStack>
  );
}
