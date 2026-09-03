import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitCommitVertical, Loader2, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import {
  listWorkflowRevisions,
  restoreWorkflowRevision,
  type Workflow,
  type WorkflowRevision,
} from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { relativeTime } from "@/lib/time";

const SOURCE_LABELS: Record<string, MessageKey> = {
  create: "wfRevisionSourceCreate",
  edit: "wfRevisionSourceEdit",
  restore: "wfRevisionSourceRestore",
  import: "wfRevisionSourceImport",
  template: "wfRevisionSourceTemplate",
  agent: "wfRevisionSourceAgent",
  migration: "wfRevisionSourceMigration",
};

function absoluteTime(iso: string, locale: string): string {
  const normalized = /Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  return new Date(normalized).toLocaleString(locale);
}

export function WorkflowRevisionHistory({
  workflow,
  open,
  onOpenChange,
  onRestored,
}: {
  workflow: Workflow;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRestored: (workflow: Workflow) => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [pending, setPending] = React.useState<WorkflowRevision | null>(null);
  const revisions = useQuery({
    queryKey: ["workflow-revisions", workflow.id],
    queryFn: () => listWorkflowRevisions(workflow.id),
    enabled: open,
  });
  const restore = useMutation({
    mutationFn: (revision: number) => restoreWorkflowRevision(workflow.id, revision),
    onSuccess: (saved) => {
      setPending(null);
      onOpenChange(false);
      onRestored(saved);
      void qc.invalidateQueries({ queryKey: ["workflow-revisions", workflow.id] });
      void qc.invalidateQueries({ queryKey: ["workflows", workflow.workspace_id] });
      toast.success(t("wfRevisionRestored").replace("{version}", String(saved.revision)));
    },
    onError: (error: Error) => toast.error(t("wfRevisionRestoreFailed"), { description: error.message }),
  });

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!restore.isPending) onOpenChange(next);
        }}
      >
        <DialogContent className="max-h-[min(720px,calc(100vh-32px))] w-[min(620px,calc(100vw-32px))] max-w-[calc(100vw-32px)] grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-0">
          <DialogHeader className="border-b border-border px-5 pb-4 pt-5 pr-12">
            <DialogTitle className="flex items-center gap-2 text-ui-lg">
              <GitCommitVertical size={17} className="text-primary" />
              {t("wfRevisionHistory")}
              <Badge variant="secondary" className="ml-1 px-1.5 py-0 font-mono text-ui-2xs">
                v{workflow.revision}
              </Badge>
            </DialogTitle>
            <DialogDescription>{t("wfRevisionHistoryDesc")}</DialogDescription>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto p-3">
            {revisions.isLoading && (
              <div className="grid min-h-40 place-items-center text-muted-foreground">
                <Loader2 size={18} className="animate-mosael-spin" />
              </div>
            )}
            {revisions.isError && (
              <div className="grid min-h-40 place-items-center px-8 text-center text-ui-sm text-destructive">
                {revisions.error.message}
              </div>
            )}
            <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
              {(revisions.data ?? []).map((item) => {
                const current = item.revision === workflow.revision;
                const sameContent = item.graph_hash === workflow.graph_hash;
                const sourceKey = SOURCE_LABELS[item.source];
                return (
                  <li
                    key={item.id}
                    className={cn(
                      "flex min-w-0 items-center gap-3 rounded-lg border border-border bg-background px-3 py-2.5",
                      current && "border-primary/45 bg-accent/45",
                    )}
                  >
                    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-border bg-panel font-mono text-ui-xs font-semibold">
                      {item.revision}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex min-w-0 items-center gap-2">
                        <span className="font-medium">v{item.revision}</span>
                        <span className="truncate text-ui-xs text-muted-foreground">
                          {sourceKey ? t(sourceKey) : item.source}
                        </span>
                        {current && (
                          <Badge variant="outline" className="px-1.5 py-0 text-ui-2xs text-primary">
                            {t("wfRevisionCurrent")}
                          </Badge>
                        )}
                      </div>
                      <div className="mt-0.5 flex min-w-0 items-center gap-2 text-ui-2xs text-muted-foreground">
                        <time title={absoluteTime(item.created_at, locale)}>
                          {relativeTime(item.created_at, locale)}
                        </time>
                        <span aria-hidden>·</span>
                        <span className="truncate font-mono" title={item.graph_hash}>
                          {item.graph_hash.slice(0, 10)}
                        </span>
                        {item.note && (
                          <>
                            <span aria-hidden>·</span>
                            <span className="truncate" title={item.note}>
                              {item.note}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      className="shrink-0"
                      disabled={sameContent || restore.isPending}
                      onClick={() => setPending(item)}
                    >
                      <RotateCcw size={13} />
                      {t("wfRevisionRestore")}
                    </Button>
                  </li>
                );
              })}
            </ol>
          </div>
        </DialogContent>
      </Dialog>

      <AlertDialog open={pending !== null} onOpenChange={(next) => !next && !restore.isPending && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("wfRevisionRestoreConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("wfRevisionRestoreConfirmDesc").replace("{version}", String(pending?.revision ?? ""))}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={restore.isPending}>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={restore.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (pending) restore.mutate(pending.revision);
              }}
            >
              {restore.isPending && <Loader2 size={13} className="animate-mosael-spin" />}
              {t("wfRevisionRestoreAsNew")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
