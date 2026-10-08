import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleAlert, Plus, TriangleAlert } from "lucide-react";

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
import { ResultsSection } from "@/features/plugins/appForm/FormBuilder";
import { FormsBar } from "@/features/plugins/appForm/FormsBar";
import {
  annotatePayload,
  appendForm,
  blankForm,
  dropAllInvalid,
  initialDraft,
  isStale,
  replaceForm,
  sameDraft,
  toggleResult,
  untitled,
  type FormsDraft,
} from "@/features/plugins/workflowAppForm";

/** 打开编辑器时停到哪张:某一张表单(它的 id),「新表单」(进来就加一张空白的),或者第一张。 */
export type FormFocus = { form: string } | { new: true } | null;

/**
 * 表单编辑器(ADR 0038 §2、ADR 0045 §7):工作流库详情里的「编辑表单」。对应 RunningHub 的「AI 应用」—— 作者从一张工作流**全部能填的
 * 项**里挑出要给别人填的几项、起名、排序、收窄可选值;一张工作流可以有几张表单,各是它的一个入口(AI 工作台、画板、工作流节点里各是
 * 一项,完整工作流那一项永远在)。
 *
 * 头上是「结果取自」(按工作流记,完整工作流和每张表单都按它)和表单那一排(切换、新表单、复制、删除),下面是选中那张的标题、说明
 * 和编辑器正文 {@link AppFormEditor}:工作流里能填的 / 表单 / 预览。尾上是有没有没存的修改、取消、保存。存进**那张工作流自己的文件
 * 里**,每次交全部表单:先确认,写明哪台服务器上的哪个文件、只改表单这部分;带着读到时的改动时间去,那台机器上在这之间存过(409
 * stale)就不写,说清楚、给「重新打开」。每张表单都要有标题才存得了。有没存的修改时关掉要先确认放弃。网页版也一样 —— 不依赖内嵌画布。
 */
export function WorkflowAppEditor({
  instance,
  flow,
  workspaceId,
  focus = null,
  onClose,
  onSaved,
}: {
  instance: PluginInstance;
  flow: WorkflowFile;
  /** 删表单前数「这个工作区里有几处在用它」 */
  workspaceId?: string;
  focus?: FormFocus;
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
  const [draft, setDraft] = React.useState<FormsDraft | null>(null);
  const [base, setBase] = React.useState<FormsDraft | null>(null);
  const [selected, setSelected] = React.useState("");
  const [asking, setAsking] = React.useState(false);
  const [discarding, setDiscarding] = React.useState(false);
  const [failure, setFailure] = React.useState<{ stale: boolean; message: string } | null>(null);
  const focused = React.useRef(focus);
  React.useEffect(() => {
    if (!query.data) return;
    const read = initialDraft(query.data);
    const wanted = focused.current;
    focused.current = null;
    const added = wanted && "new" in wanted ? blankForm() : null;
    setBase(read);
    setDraft(added ? appendForm(read, added) : read);
    const named = wanted && "form" in wanted ? read.forms.find((one) => one.id === wanted.form) : undefined;
    setSelected(added?.key ?? named?.key ?? read.forms[0]?.key ?? "");
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
  const nameless = draft ? untitled(draft) : [];
  const canSave = Boolean(data?.editable && draft && dirty && nameless.length === 0 && data.modified != null && !save.isPending);
  const change = (next: FormsDraft) => {
    setFailure(null);
    setDraft(next);
  };
  const current = draft?.forms.find((one) => one.key === selected) ?? null;
  const close = () => (dirty ? setDiscarding(true) : onClose());
  const footer = (
    <>
      {dirty && (
        <span role="status" data-app-dirty="" className="inline-flex items-center gap-1.5 text-ui-xs font-medium text-warning sm:mr-auto">
          <span aria-hidden className="size-1.5 rounded-full bg-warning" />
          {nameless.length > 0 ? t("workflowFormsUntitled").replace("{n}", String(nameless.length)) : t("workflowAppDirty")}
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
  } else if (current) {
    body = (
      <AppFormEditor instance={instance} data={data} draft={current}
                     onChange={(next) => change(replaceForm(draft, current.key, next))} />
    );
  } else {
    body = <NoForms onNew={() => {
      const added = blankForm();
      change(appendForm(draft, added));
      setSelected(added.key);
    }} />;
  }

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !save.isPending && close()}
      title={t("workflowAppTitle").replace("{name}", flow.label)}
      header={data && draft ? (
        <div className="grid min-w-0 gap-3">
          <ResultsSection outputs={data.outputs ?? []} results={draft.results}
                          onToggle={(node) => change(toggleResult(draft, node))} />
          <FormsBar data={data} draft={draft} selected={selected} instanceId={instance.id} workspaceId={workspaceId}
                    onSelect={setSelected} onChange={(next, select) => {
                      change(next);
                      setSelected(select);
                    }} />
          {current && (
            <AppHead draft={current} onChange={(next) => change(replaceForm(draft, current.key, next))}
                     where={t("workflowAppWhere").replace("{server}", instance.name)} />
          )}
        </div>
      ) : undefined}
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
          body={draft.forms.length > 0 ? t("workflowAppSaveBody") : t("workflowAppSaveRemoveBody")}
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

/** 一张表单都没有:用的人看到的是完整工作流(全部能填的项);给一颗「新表单」。 */
export function NoForms({ onNew }: { onNew: () => void }) {
  const t = useI18n();
  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 text-center" data-no-forms="">
      <p className="m-0 max-w-md text-ui-sm leading-relaxed text-muted-foreground">{t("workflowFormsEmpty")}</p>
      <Button variant="outline" size="sm" onClick={onNew}>
        <Plus size={14} />
        {t("workflowFormNew")}
      </Button>
    </div>
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
 * 工作流库详情里「表单」那一节:每张表单一行(标题 —— 没起的写「未命名表单」—— 几项、几项失效),点哪张打开那张的编辑器;「新表单」
 * 打开编辑器、进来就加一张空白的。标成结果的节点写一行。对不上的那几项(工作流在 ComfyUI 里改过了)能**一键去掉**(先确认,
 * 和存一样只改 mosael 那几处标记、带着改动时间去)。表单还是上一版的格式时说清楚要升级(工作流库顶上那条横幅里升级)。
 * 插件没报表单(这张转不过来)就不出这一节。
 */
export function WorkflowAppSection({
  instance,
  flow,
  onEdit,
  onUpgrade,
  onSaved,
}: {
  instance: PluginInstance;
  flow: WorkflowFile;
  onEdit: (focus: FormFocus) => void;
  /** 表单还是上一版的格式:打开「查看并升级」 */
  onUpgrade: () => void;
  onSaved: () => void;
}) {
  const t = useI18n();
  const [asking, setAsking] = React.useState(false);
  const [failure, setFailure] = React.useState("");
  const drop = useMutation({
    mutationFn: async () => {
      const data = await getWorkflowApp(instance.id, flow.path);
      const draft = dropAllInvalid(initialDraft(data), (data.outputs ?? []).map((one) => one.node ?? ""));
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
  const forms = app.status === "ok" ? app.forms ?? [] : [];
  return (
    <LibrarySection
      title={t("workflowApp")}
      count={forms.length || undefined}
      action={app.status === "unsupported" ? undefined : (
        <Hint label={t("workflowAppEditHint")}>
          <Button variant="outline" size="sm" onClick={() => onEdit({ new: true })} data-forms-new-from-detail="">
            <Plus size={14} />
            {t("workflowFormNew")}
          </Button>
        </Hint>
      )}
    >
      {app.status === "unsupported" ? (
        <div className="grid gap-2">
          <Notice>
            {app.upgradable ? t("workflowAppUpgradeNeeded") : t("workflowAppUnsupported").replace("{version}", app.version || "?")}
          </Notice>
          {app.upgradable && (
            <Button variant="outline" size="sm" className="justify-self-start" onClick={onUpgrade}>
              {t("workflowFormsUpgradeOpen")}
            </Button>
          )}
        </div>
      ) : forms.length > 0 ? (
        <ul aria-label={t("workflowFormsBar")} className="m-0 grid list-none gap-1.5 p-0" data-detail-forms="">
          {forms.map((form) => (
            <li key={form.id}>
              <button type="button" onClick={() => onEdit({ form: form.id })} data-detail-form={form.id}
                      className="flex w-full min-w-0 items-center gap-2 rounded-lg border border-border px-3 py-2 text-left hover:bg-secondary">
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <Truncate className={form.title ? "text-ui-sm font-medium text-foreground" : "text-ui-sm italic text-muted-foreground"}>
                    {form.title || t("workflowFormUntitled")}
                  </Truncate>
                  {form.description && (
                    <span className="text-ui-xs text-muted-foreground"><InlineMarkdown text={form.description} /></span>
                  )}
                </span>
                <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">
                  {t("workflowFormFields").replace("{n}", String(form.fields ?? 0))}
                </span>
                {(form.invalid ?? 0) > 0 && (
                  <span className="inline-flex shrink-0 items-center gap-1 text-ui-xs text-warning">
                    <TriangleAlert size={12} aria-hidden />
                    {t("workflowFormInvalid").replace("{n}", String(form.invalid))}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppNone")}</p>
      )}
      {(app.results ?? []).length > 0 && app.status === "ok" && (
        <p className="m-0 text-ui-xs text-muted-foreground">
          {t("workflowAppResultsMarked").replace("{nodes}", (app.results ?? []).map((one) => `#${one}`).join(t("listSeparator")))}
        </p>
      )}
      {app.status === "ok" && (app.stray ?? 0) > 0 && (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowFormStray").replace("{n}", String(app.stray))}</p>
      )}
      {app.status === "ok" && (app.invalid ?? 0) > 0 && (
        <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
          <span className="flex items-start gap-2">
            <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
            <span className="min-w-0">{t("workflowAppInvalidCount").replace("{n}", String(app.invalid))}</span>
          </span>
          <ul className="m-0 grid list-none gap-1 p-0 text-ui-xs text-muted-foreground">
            {forms.flatMap((form) => (form.items ?? []).filter((one) => one.problem).map((one) => (
              <li key={`${form.id}:${one.key}`} className="break-words">
                {t("workflowAppInvalidItem").replace("{name}", `${form.title || t("workflowFormUntitled")} · ${one.label || one.key}`)
                  .replace("{why}", one.problem ?? "")}
              </li>
            )))}
          </ul>
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
