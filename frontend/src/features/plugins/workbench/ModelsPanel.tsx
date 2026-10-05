import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, MousePointerClick, RefreshCcw, Search } from "lucide-react";

import { getModelLibrary, getNodeFolders, resolveModelLink, startModelDownload, type ModelFile, type ModelResolved } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { ModelThumb, modelBaseName } from "@/components/generation/ModelThumb";
import { LoadingState } from "@/components/layout/LoadingState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Truncate } from "@/components/ui/truncate";
import {
  comboInputs,
  folderFamilies,
  folderModels,
  modelSlots,
  presentIn,
  type ModelSlot,
  type WorkbenchNode,
} from "@/features/plugins/workbench/workbenchLogic";
import { InlineConfirm, PanelNote, useJobWatch, useOnJobDone } from "@/features/plugins/workbench/workbenchParts";
import { workbenchCall, type WorkbenchTarget } from "@/features/plugins/workbench/workbenchSession";
import { usePersistentTab } from "@/lib/usePersistentTab";
import { cn } from "@/lib/utils";

/** 一次最多摆多少个(一个目录里见过几百个 LoRA):多了先搜。 */
const LISTED = 120;

/**
 * 工作台的「模型库」面板(ADR 0038 §6):在画布上选中一个加载节点 → 问插件它那几格选的是哪个模型目录的文件 → 用模型库的数据
 * 只列那个目录的(缩略图、底模家族、触发词),能搜、能按家族筛 → 点一个,经桥填进那一格(桥先查它在下拉里)。现在那一格选的
 * 文件这台 ComfyUI 上没有,就地贴个链接下到那个目录;下完经桥刷新下拉,新文件出现在下拉里。
 */
export function ModelsPanel({
  target,
  node,
  capabilities,
}: {
  target: WorkbenchTarget;
  node: WorkbenchNode | null;
  capabilities: ComfyWorkbenchState["capabilities"] | null;
}) {
  const t = useI18n();
  const inputs = React.useMemo(() => comboInputs(node), [node]);
  const folders = useQuery({
    queryKey: ["comfy-node-folders", target.instanceId, inputs.map((one) => `${one.class_type}:${one.input}`).join("|")],
    queryFn: () => getNodeFolders(target.instanceId, inputs),
    enabled: inputs.length > 0,
    staleTime: Infinity,
  });
  const library = useQuery({
    queryKey: ["model-library", target.instanceId],
    queryFn: () => getModelLibrary(target.instanceId),
    staleTime: 30_000,
  });
  const slots = modelSlots(node, folders.data?.folders ?? []);

  if (capabilities && (!capabilities.selection || !capabilities.setWidget)) {
    return <PanelNote tone="warning">{t("workbenchUnsupported").replace("{what}", t("workbenchCapSelection"))}</PanelNote>;
  }
  if (!node) {
    return (
      <div className="grid justify-items-center gap-2 px-4 py-10 text-center text-ui-sm text-muted-foreground">
        <MousePointerClick size={20} aria-hidden />
        <p className="m-0 leading-relaxed">{t("workbenchModelsPick")}</p>
      </div>
    );
  }
  if (folders.isPending && inputs.length > 0) return <LoadingState label={t("workbenchModelsLoading")} className="h-auto py-8" />;
  if (folders.isError) return <PanelNote tone="error">{errorText(folders.error)}</PanelNote>;
  if (slots.length === 0) {
    return <PanelNote>{t("workbenchModelsNoSlot").replace("{node}", node.title || node.type)}</PanelNote>;
  }
  return (
    <div className="grid gap-4">
      {slots.map((slot) => (
        <SlotPicker
          key={`${node.id}:${slot.widget}`}
          target={target}
          node={node}
          slot={slot}
          models={library.data?.models ?? []}
          loading={library.isPending}
          error={library.isError ? errorText(library.error) : ""}
          canRefresh={capabilities?.refreshCombos !== false}
        />
      ))}
    </div>
  );
}

function SlotPicker({
  target,
  node,
  slot,
  models,
  loading,
  error,
  canRefresh,
}: {
  target: WorkbenchTarget;
  node: WorkbenchNode;
  slot: ModelSlot;
  models: ModelFile[];
  loading: boolean;
  error: string;
  canRefresh: boolean;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [query, setQuery] = React.useState("");
  const [family, setFamily] = React.useState("");
  const [note, setNote] = React.useState<{ tone: "info" | "warning" | "error"; text: string; refresh?: boolean } | null>(null);
  //: 模型库的「模糊预览图」记在本机,这里照着它
  const [blur] = usePersistentTab<"on" | "off">("model-library.blur", "off", ["on", "off"]);
  const families = folderFamilies(models, slot.folder);
  const listed = folderModels(models, slot.folder, { query, family });
  const present = presentIn(models, slot.folder, slot.value);

  const pick = useMutation({
    mutationFn: (model: ModelFile) =>
      workbenchCall({ op: "setWidget", node: node.id, widget: slot.widget, value: model.name }),
    onMutate: () => setNote(null),
    onSuccess: (result, model) => {
      if (result.ok) setNote({ tone: "info", text: t("workbenchModelsFilled").replace("{name}", modelBaseName(model.name)) });
      else if (result.error === "notInList") setNote({ tone: "warning", text: t("workbenchModelsNotInList"), refresh: true });
      else setNote({ tone: "error", text: t("workbenchCallFailed").replace("{why}", "message" in result && result.message ? result.message : result.error) });
    },
  });
  const refresh = useMutation({
    mutationFn: () => workbenchCall({ op: "refreshCombos" }),
    onSuccess: (result) => {
      setNote(result.ok ? { tone: "info", text: t("workbenchCombosRefreshed") } : { tone: "error", text: t("workbenchCallFailed").replace("{why}", result.error) });
      void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
    },
  });

  return (
    <section aria-label={`${slot.widget} · ${slot.folder}`} className="grid gap-2.5">
      <header className="grid gap-1">
        <h3 className="m-0 flex min-w-0 items-center gap-1.5 text-ui-sm font-semibold text-foreground">
          <Truncate>{node.title || node.type}</Truncate>
          <span className="shrink-0 text-ui-xs font-normal text-muted-foreground">#{node.id} · {slot.widget}</span>
        </h3>
        <div className="flex min-w-0 items-center gap-1.5 text-ui-xs text-muted-foreground">
          <span className="shrink-0">{t("workbenchModelsCurrent")}</span>
          <Truncate className="min-w-0 text-foreground">{slot.value || "—"}</Truncate>
          {!loading && !error && !present && <CatalogBadge tone="warning">{t("workbenchModelsMissing")}</CatalogBadge>}
        </div>
      </header>
      {note && (
        <PanelNote
          tone={note.tone}
          action={note.refresh && canRefresh ? (
            <Button variant="outline" size="xs" className="shrink-0" loading={refresh.isPending} onClick={() => refresh.mutate()}>
              <RefreshCcw size={12} />
              {t("workbenchCombosRefresh")}
            </Button>
          ) : undefined}
        >
          {note.text}
        </PanelNote>
      )}
      {!loading && !error && !present && (
        <DownloadBox target={target} folder={slot.folder} wanted={slot.value} canRefresh={canRefresh}
                     onDone={() => {
                       void qc.invalidateQueries({ queryKey: ["model-library", target.instanceId] });
                       if (canRefresh) refresh.mutate();
                     }} />
      )}
      <label className="relative">
        <Search size={13} aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input size="xs" className="pl-8" value={query} placeholder={t("workbenchModelsSearch").replace("{folder}", slot.folder)}
               aria-label={t("workbenchModelsSearch").replace("{folder}", slot.folder)} onChange={(event) => setQuery(event.target.value)} />
      </label>
      {families.length > 1 && (
        <div role="group" aria-label={t("workbenchModelsFamily")} className="flex flex-wrap gap-1">
          {["", ...families].map((one) => (
            <button
              key={one || "all"}
              type="button"
              aria-pressed={family === one}
              className={cn(
                "h-6 cursor-pointer rounded-full border px-2 text-ui-xs",
                family === one ? "border-primary/50 bg-accent text-primary" : "border-border bg-transparent text-muted-foreground hover:bg-secondary",
              )}
              onClick={() => setFamily(one)}
            >
              {one || t("workbenchModelsFamilyAll")}
            </button>
          ))}
        </div>
      )}
      {loading ? (
        <LoadingState label={t("workbenchModelsLoading")} className="h-auto py-6" />
      ) : error ? (
        <PanelNote tone="error">{error}</PanelNote>
      ) : listed.length === 0 ? (
        <p className="m-0 text-ui-xs text-muted-foreground">{t("workbenchModelsEmpty")}</p>
      ) : (
        <ul aria-label={t("workbenchModelsList").replace("{folder}", slot.folder)} className="m-0 grid list-none gap-1 p-0">
          {listed.slice(0, LISTED).map((model) => {
            const chosen = model.name.replace(/\\/g, "/") === slot.value.replace(/\\/g, "/");
            return (
              <li key={model.name}>
                <button
                  type="button"
                  aria-pressed={chosen}
                  disabled={pick.isPending}
                  className={cn(
                    "group/thumb flex w-full min-w-0 cursor-pointer items-center gap-2.5 rounded-lg border p-1.5 text-left",
                    chosen ? "border-primary/50 bg-accent" : "border-transparent hover:bg-secondary",
                  )}
                  onClick={() => pick.mutate(model)}
                >
                  <span className="size-11 shrink-0 overflow-hidden rounded-md [&>*]:size-full">
                    <ModelThumb compact instanceId={target.instanceId} model={model} blurred={blur === "on"} />
                  </span>
                  <span className="grid min-w-0 flex-1 gap-0.5">
                    <Truncate className="text-ui-xs font-medium text-foreground">{model.title || modelBaseName(model.name)}</Truncate>
                    <span className="flex min-w-0 items-center gap-1 text-ui-2xs text-muted-foreground">
                      {model.family && <CatalogBadge tone="muted">{model.family}</CatalogBadge>}
                      <Truncate>{(model.triggers ?? []).slice(0, 3).join(", ") || modelBaseName(model.name)}</Truncate>
                    </span>
                  </span>
                  {chosen && <Check size={14} aria-hidden className="shrink-0 text-primary" />}
                </button>
              </li>
            );
          })}
          {listed.length > LISTED && (
            <li className="px-1.5 text-ui-xs text-muted-foreground">
              {t("workbenchModelsMore").replace("{n}", String(listed.length - LISTED))}
            </li>
          )}
        </ul>
      )}
    </section>
  );
}

/** 那一格选的文件这台 ComfyUI 上没有:贴个链接(HuggingFace / Civitai / ModelScope / 直链),认一下,确认后下到这个目录。 */
function DownloadBox({
  target,
  folder,
  wanted,
  canRefresh,
  onDone,
}: {
  target: WorkbenchTarget;
  folder: string;
  wanted: string;
  canRefresh: boolean;
  onDone: () => void;
}) {
  const t = useI18n();
  const [link, setLink] = React.useState("");
  const [resolved, setResolved] = React.useState<ModelResolved | null>(null);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const job = useJobWatch(jobId);
  useOnJobDone(job.data, (done) => {
    if (done.status === "succeeded") onDone();
  });
  const resolve = useMutation({ mutationFn: () => resolveModelLink(target.instanceId, link.trim()), onSuccess: setResolved });
  const start = useMutation({
    mutationFn: () =>
      startModelDownload(target.instanceId, {
        workspace_id: target.workspaceId,
        url: resolved!.url,
        folder,
        filename: resolved!.filename || modelBaseName(wanted),
      }),
    onSuccess: (created) => {
      setResolved(null);
      setJobId(created.id);
    },
  });
  if (jobId) {
    const status = job.data?.status ?? "queued";
    return (
      <PanelNote tone={status === "failed" ? "error" : "info"}>
        {status === "succeeded"
          ? t(canRefresh ? "workbenchDownloadDone" : "workbenchDownloadDoneManual")
          : status === "failed" ? job.data?.error || t("workbenchDownloadFailed")
          : `${t("workbenchDownloading")} ${job.data?.message ?? ""}`}
      </PanelNote>
    );
  }
  return (
    <div className="grid gap-2 rounded-lg border border-dashed border-border p-2.5">
      <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">
        {t("workbenchDownloadHint").replace("{name}", modelBaseName(wanted)).replace("{folder}", folder)}
      </p>
      <div className="flex gap-1.5">
        <Input size="xs" className="min-w-0 flex-1" value={link} placeholder={t("workbenchDownloadLink")}
               aria-label={t("workbenchDownloadLink")} onChange={(event) => setLink(event.target.value)} />
        <Button variant="outline" size="xs" disabled={!/^https?:\/\//i.test(link.trim())} loading={resolve.isPending}
                onClick={() => resolve.mutate()}>
          {t("workbenchDownloadResolve")}
        </Button>
      </div>
      {resolve.isError && <PanelNote tone="error">{errorText(resolve.error)}</PanelNote>}
      {start.isError && <PanelNote tone="error">{errorText(start.error)}</PanelNote>}
      {resolved && (
        <InlineConfirm
          title={t("workbenchDownloadConfirm").replace("{server}", target.instanceName).replace("{folder}", folder)
            .replace("{name}", resolved.filename || modelBaseName(wanted))}
          body={resolved.exists ? t("workbenchDownloadExists") : undefined}
          confirmLabel={t("workbenchDownloadStart")}
          pending={start.isPending}
          onCancel={() => setResolved(null)}
          onConfirm={() => start.mutate()}
        />
      )}
    </div>
  );
}
