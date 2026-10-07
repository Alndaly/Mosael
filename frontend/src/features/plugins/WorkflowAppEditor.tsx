import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleAlert, TriangleAlert } from "lucide-react";

import { annotateWorkflow, getWorkflowApp, type PluginInstance, type WorkflowFile } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { LibrarySection } from "@/components/app/LibraryBrowser";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { PageLoadError } from "@/components/layout/EmptyState";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { AppFormEditor, AppHead } from "@/features/plugins/appForm/AppFormEditor";
import {
  annotatePayload,
  dropInvalid,
  initialDraft,
  isStale,
  sameDraft,
  type AppDraft,
} from "@/features/plugins/workflowAppForm";

/**
 * 应用表单编辑器(ADR 0038 §2、§8 第一刀):工作流库详情里的「编辑应用表单」。对应 RunningHub 的「AI 应用」——作者从一张工作流
 * **全部能填的项**里挑出要给别人填的几项、起名、排序、收窄可选值,标结果取自哪个节点;AI 工作台、画板、工作流节点选这张工作流时
 * 都用这张表(它们不认识「应用」,读的还是同一个描述符,只是短了)。正文是 {@link AppFormEditor}:工作流里能填的 / 表单 / 预览。
 *
 * 头上钉着应用名、说明和一行「存在哪」的大白话;尾上是有没有没存的修改、取消、保存。存进**那张工作流自己的文件里**:每次存都先确认,
 * 写明哪台服务器上的哪个文件、只改应用表单这部分;带着读到时的改动时间去,那台机器上在这之间存过(409 stale)就不写,说清楚、给
 * 「重新打开」。有没存的修改时关掉要先确认放弃。网页版也一样 —— 不依赖内嵌画布。
 */
export function WorkflowAppEditor({
  instance,
  flow,
  onClose,
  onSaved,
}: {
  instance: PluginInstance;
  flow: WorkflowFile;
  onClose: () => void;
  /** 存成了:工作流库、生成选项要重新问(宿主已经让这个连接的目录重拉过) */
  onSaved: () => void;
}) {
  const t = useI18n();
  const query = useQuery({
    queryKey: ["workflow-app", instance.id, flow.path],
    queryFn: () => getWorkflowApp(instance.id, flow.path),
    staleTime: 0,
  });
  const [draft, setDraft] = React.useState<AppDraft | null>(null);
  const [base, setBase] = React.useState<AppDraft | null>(null);
  const [asking, setAsking] = React.useState(false);
  const [discarding, setDiscarding] = React.useState(false);
  const [failure, setFailure] = React.useState<{ stale: boolean; message: string } | null>(null);
  React.useEffect(() => {
    if (!query.data) return;
    const next = initialDraft(query.data);
    setDraft(next);
    setBase(next);
  }, [query.data]);

  const save = useMutation({
    mutationFn: (payload: Parameters<typeof annotateWorkflow>[1]) => annotateWorkflow(instance.id, payload),
    onSuccess: () => {
      setAsking(false);
      onSaved();
      onClose();
    },
    onError: (error) => {
      setAsking(false);
      setFailure({ stale: isStale(error), message: errorText(error) });
    },
  });

  const data = query.data;
  const dirty = Boolean(draft && base && !sameDraft(draft, base));
  const canSave = Boolean(data?.editable && draft && dirty && data.modified != null && !save.isPending);
  const change = (next: AppDraft) => {
    setFailure(null);
    setDraft(next);
  };
  const close = () => (dirty ? setDiscarding(true) : onClose());
  const footer = (
    <>
      {dirty && (
        <span role="status" data-app-dirty="" className="inline-flex items-center gap-1.5 text-ui-xs font-medium text-warning sm:mr-auto">
          <span aria-hidden className="size-1.5 rounded-full bg-warning" />
          {t("workflowAppDirty")}
        </span>
      )}
      <Button variant="ghost" disabled={save.isPending} onClick={close}>{t("cancel")}</Button>
      <Button disabled={!canSave} loading={save.isPending} onClick={() => setAsking(true)}>
        {t("workflowAppSave")}
      </Button>
    </>
  );

  let body: React.ReactNode;
  if (query.isPending) {
    body = <LoadingState label={t("workflowAppLoading")} />;
  } else if (query.isError || !data || !draft) {
    body = (
      <div className="flex min-h-0 flex-1 items-center justify-center">
      <PageLoadError
        size="section"
        icon={<CircleAlert />}
        title={t("workflowAppLoadFailed")}
        error={query.error}
        onRetry={() => void query.refetch()}
        retrying={query.isFetching}
      />
      </div>
    );
  } else {
    body = <AppFormEditor instance={instance} data={data} draft={draft} onChange={change} />;
  }

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !save.isPending && close()}
      title={t("workflowAppTitle").replace("{name}", flow.label)}
      header={draft ? <AppHead draft={draft} onChange={change} where={t("workflowAppWhere").replace("{server}", instance.name)} /> : undefined}
      //: 高度定死:读着、读不到、编辑三种样子一样高,不随内容跳(此前读着的时候矮一截,读完猛地撑高)
      className="h-[min(1060px,90vh)] w-[min(1320px,calc(100vw-32px))]"
      footer={footer}
    >
      <div className="flex h-full min-h-0 min-w-0 flex-col gap-3">
        {failure && (
          <div role="alert" className="flex min-w-0 items-start gap-2 rounded-lg border border-destructive/40 bg-panel p-3 text-ui-sm">
            <CircleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-destructive" />
            <span className="min-w-0 flex-1 break-words">
              {failure.stale ? t("workflowAppStale").replace("{name}", flow.label) : failure.message}
            </span>
            {failure.stale && (
              <Button variant="outline" size="sm" className="shrink-0" onClick={() => {
                setFailure(null);
                void query.refetch();
              }}>
                {t("workflowAppReload")}
              </Button>
            )}
          </div>
        )}
        {body}
      </div>
      {asking && data && draft && (
        <ConfirmDialog
          open
          title={t("workflowAppSaveTitle").replace("{server}", instance.name).replace("{path}", data.path)}
          body={draft.items.length > 0 ? t("workflowAppSaveBody") : t("workflowAppSaveRemoveBody")}
          confirmLabel={t("workflowAppSaveConfirm")}
          pending={save.isPending}
          onCancel={() => setAsking(false)}
          onConfirm={() => save.mutate(annotatePayload(data.path, data.modified ?? 0, draft))}
        />
      )}
      {discarding && (
        <ConfirmDialog
          open
          title={t("workflowAppDiscardTitle")}
          body={t("workflowAppDiscardBody")}
          confirmLabel={t("workflowAppDiscardConfirm")}
          pending={false}
          onCancel={() => setDiscarding(false)}
          onConfirm={() => {
            setDiscarding(false);
            onClose();
          }}
        />
      )}
    </ModalShell>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div role="status" className="flex min-w-0 items-start gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
      <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}

/**
 * 工作流库详情里「应用」那一节:有没有应用表单、叫什么、几项、标成结果的节点;对不上的那几项列出来(工作流在 ComfyUI 里
 * 改过了),能**一键去掉**(先确认,和存一样只改 mosael 那几处标记、带着改动时间去)。「编辑应用表单」打开编辑器。
 * 插件没报应用表单(这张转不过来)就不出这一节。
 */
export function WorkflowAppSection({
  instance,
  flow,
  onEdit,
  onSaved,
}: {
  instance: PluginInstance;
  flow: WorkflowFile;
  onEdit: () => void;
  onSaved: () => void;
}) {
  const t = useI18n();
  const [asking, setAsking] = React.useState(false);
  const [failure, setFailure] = React.useState("");
  const drop = useMutation({
    mutationFn: async () => {
      const data = await getWorkflowApp(instance.id, flow.path);
      const draft = dropInvalid(initialDraft(data), (data.outputs ?? []).map((one) => one.node ?? ""));
      return annotateWorkflow(instance.id, annotatePayload(data.path, data.modified ?? 0, draft));
    },
    onSuccess: () => {
      setAsking(false);
      onSaved();
    },
    onError: (error) => {
      setAsking(false);
      setFailure(isStale(error) ? t("workflowAppStale").replace("{name}", flow.label) : errorText(error));
    },
  });
  const app = flow.app;
  if (!app) return null;
  const broken = (app.items ?? []).filter((one) => one.problem);
  return (
    <LibrarySection
      title={t("workflowApp")}
      count={app.app ? app.fields : undefined}
      action={
        <Hint label={t("workflowAppEditHint")}>
          <Button variant="outline" size="sm" onClick={onEdit}>{t("workflowAppEdit")}</Button>
        </Hint>
      }
    >
      {app.status === "unsupported" ? (
        <Notice>{t("workflowAppUnsupported").replace("{version}", app.version || "?")}</Notice>
      ) : app.app ? (
        <div className="grid gap-2">
          {(app.title || app.description) && (
            <p className="m-0 grid gap-0.5 text-ui-sm text-foreground">
              {app.title && <span className="font-medium">{app.title}</span>}
              {app.description && (
                <span className="text-ui-xs text-muted-foreground"><InlineMarkdown text={app.description} /></span>
              )}
            </p>
          )}
          <ul aria-label={t("workflowAppChosen")} className="m-0 flex min-w-0 list-none flex-wrap gap-1.5 p-0">
            {(app.items ?? []).filter((one) => !one.problem).map((one) => (
              <li key={one.key} className="min-w-0 max-w-full">
                <Hint label={one.key}>
                  <span className="inline-flex h-7 max-w-full items-center rounded-full bg-secondary px-2.5 text-ui-xs text-foreground">
                    <Truncate>{one.label || one.title || one.key}</Truncate>
                  </span>
                </Hint>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppNone")}</p>
      )}
      {(app.results ?? []).length > 0 && app.status === "ok" && (
        <p className="m-0 text-ui-xs text-muted-foreground">
          {t("workflowAppResultsMarked").replace("{nodes}", (app.results ?? []).map((one) => `#${one}`).join(t("listSeparator")))}
        </p>
      )}
      {app.status === "ok" && (app.invalid ?? 0) > 0 && (
        <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
          <span className="flex items-start gap-2">
            <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
            <span className="min-w-0">{t("workflowAppInvalidCount").replace("{n}", String(app.invalid))}</span>
          </span>
          {broken.length > 0 && (
            <ul className="m-0 grid list-none gap-1 p-0 text-ui-xs text-muted-foreground">
              {broken.map((one) => (
                <li key={one.key} className="break-words">
                  {t("workflowAppInvalidItem").replace("{name}", one.label || one.key).replace("{why}", one.problem ?? "")}
                </li>
              ))}
            </ul>
          )}
          <Button variant="outline" size="sm" className="justify-self-start" loading={drop.isPending}
                  onClick={() => { setFailure(""); setAsking(true); }}>
            {t("workflowAppDropInvalidSaved")}
          </Button>
        </div>
      )}
      {failure && <p role="alert" className="m-0 text-ui-sm text-destructive">{failure}</p>}
      {asking && (
        <ConfirmDialog
          open
          title={t("workflowAppSaveTitle").replace("{server}", instance.name).replace("{path}", flow.path)}
          body={t("workflowAppDropInvalidBody")}
          confirmLabel={t("workflowAppSaveConfirm")}
          pending={drop.isPending}
          onCancel={() => setAsking(false)}
          onConfirm={() => drop.mutate()}
        />
      )}
    </LibrarySection>
  );
}
