import React from "react";
import { Import, Info, TriangleAlert } from "lucide-react";

import { inspectWorkflowImport, saveImportedWorkflow, type PluginInstance, type WorkflowImport } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { CatalogBadge } from "@/components/app/CatalogDialog";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { WorkflowFacts, kindName } from "@/features/plugins/WorkflowFacts";
import { WorkflowGraphView } from "@/features/plugins/WorkflowGraph";
import { WorkflowPathField, useWorkflowPath } from "@/features/plugins/WorkflowPathField";
import { freeWorkflowPath } from "@/features/plugins/workflowLibraryView";
import { useFileDrop } from "@/lib/useFileDrop";

/** 工作流库收哪几种文件:JSON、ComfyUI 存出来的 PNG / WebP、压缩包。 */
export const WORKFLOW_IMPORT_ACCEPT = ".json,.png,.webp,.zip,application/json,image/png,image/webp,application/zip";
export const importable = (file: File) => /\.(json|png|webp|zip)$/i.test(file.name);

function base64Of(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

/**
 * 导入一张工作流(ADR 0035 §5),两步:
 *
 * 1. **交给插件认**:拖进来 / 选文件(以 base64 带着文件名)、贴一段 JSON 或一个链接(按链接交);认不出就当场说原话;
 * 2. **看预览再存**:从哪儿认出来的、什么格式(API 格式没有布局,位置是自动排的)、插件要说的话、节点图、能填什么、缺的
 *    节点和模型;路径默认是插件建议的那个(没给就自己给一个不撞名的),存进那台服务器的 workflows/ —— 不覆盖,撞名给建议名。
 *    缺的节点包、模型在存好之后的详情里装 / 下(那时这张才在那台机器上)。
 */
export function WorkflowImportDialog({
  instance,
  taken,
  initialFile,
  onClose,
  onSaved,
}: {
  instance: PluginInstance;
  /** 那台服务器上已有的路径:界面自己给名字时避开它们。 */
  taken: ReadonlySet<string>;
  /** 往工作流库上拖进来的那个文件:一打开就认它。 */
  initialFile?: File;
  onClose: () => void;
  onSaved: (path: string) => void;
}) {
  const t = useI18n();
  const [text, setText] = React.useState("");
  const [reading, setReading] = React.useState(false);
  const [error, setError] = React.useState("");
  const [found, setFound] = React.useState<WorkflowImport | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const textId = React.useId();
  const save = useWorkflowPath(
    "",
    async (path) => {
      await saveImportedWorkflow(instance.id, path, found?.workflow ?? {});
      onSaved(path);
    },
    onClose,
  );

  const inspect = async (body: { text?: string; data?: string; filename?: string; url?: string }) => {
    setReading(true);
    setError("");
    try {
      const next = await inspectWorkflowImport(instance.id, body);
      const fallback = `${t("workflowImportDefaultName")}.json`;
      setFound(next);
      save.change(next.suggested_path || (taken.has(fallback) ? freeWorkflowPath(fallback, taken) : fallback));
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setReading(false);
    }
  };
  const takeFile = async (file: File) => {
    try {
      await inspect({ data: await base64Of(file), filename: file.name });
    } catch (failure) {
      setError(errorText(failure));
    }
  };
  const takeText = () => {
    const value = text.trim();
    if (!value) return;
    void inspect(/^https?:\/\/\S+$/i.test(value) ? { url: value } : { text: value });
  };

  //: 拖进工作流库的那个文件:打开就认,只认一次
  const started = React.useRef(false);
  React.useEffect(() => {
    if (!initialFile || started.current) return;
    started.current = true;
    void takeFile(initialFile);
  });

  const drop = useFileDrop((files) => void takeFile(files[0]), importable);
  const busy = reading || save.pending;

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !busy && onClose()}
      title={t("workflowImportTitle")}
      className="w-[min(760px,calc(100vw-32px))]"
      dropzone={
        found
          ? undefined
          : {
              handlers: drop.handlers,
              overlay: drop.active ? (
                <div className="pointer-events-none absolute inset-0 z-20 grid place-items-center rounded-[inherit] bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
                  <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
                    <Import size={20} />
                    {t("workflowImportDropOverlay")}
                  </span>
                </div>
              ) : null,
            }
      }
      footer={
        found ? (
          <>
            <Button variant="ghost" disabled={busy} onClick={() => { setFound(null); setError(""); }}>
              {t("workflowImportAnother")}
            </Button>
            <Button loading={save.pending} disabled={save.bad} onClick={() => void save.submit()}>
              {t("workflowImportConfirm")}
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" disabled={busy} onClick={onClose}>{t("cancel")}</Button>
            <Button loading={reading} disabled={!text.trim()} onClick={takeText}>{t("workflowImportInspect")}</Button>
          </>
        )
      }
    >
      {found ? (
        <div className="grid gap-4">
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-ui-xs text-muted-foreground">
            <span>{t(`workflowImportSource_${found.source}`)}</span>
            <span aria-hidden>·</span>
            <span>{t(`workflowImportFormat_${found.format}`)}</span>
            <span aria-hidden>·</span>
            <CatalogBadge tone={found.problem ? "warning" : found.kind ? "primary" : "muted"}>{kindName(t, found.kind)}</CatalogBadge>
            <span className="tabular-nums">{t("workflowLibraryNodes").replace("{n}", String(found.node_count))}</span>
          </div>
          {(found.notes ?? []).map((note) => (
            <div key={note} className="flex min-w-0 items-start gap-2 rounded-lg border border-border bg-panel p-3 text-ui-sm text-foreground">
              <Info size={14} aria-hidden className="mt-0.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 break-words">{note}</span>
            </div>
          ))}
          <WorkflowGraphView
            graph={found.graph}
            detailed
            label={t("workflowGraphLabel").replace("{name}", save.value || t("workflowImportDefaultName"))}
            className="aspect-[16/9] w-full rounded-xl"
          />
          {found.problem && (
            <div className="flex min-w-0 items-start gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
              <TriangleAlert size={14} aria-hidden className="mt-0.5 shrink-0 text-warning" />
              <span className="min-w-0 break-words">{found.problem}</span>
            </div>
          )}
          <WorkflowFacts facts={found} />
          {((found.missing_nodes?.length ?? 0) > 0 || (found.missing_models?.length ?? 0) > 0) && (
            <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowImportAfter")}</p>
          )}
          <div className="grid gap-3 border-t border-border pt-4">
            <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">
              {t("workflowWriteWhere").replace("{server}", instance.name)}
            </p>
            <WorkflowPathField state={save} />
          </div>
        </div>
      ) : (
        <div className="grid gap-4">
          <div className="grid justify-items-center gap-2 rounded-xl border-2 border-dashed border-border px-6 py-8 text-center">
            <Import size={22} aria-hidden className="text-muted-foreground" />
            <p className="m-0 text-ui-sm font-medium text-foreground">{t("workflowImportDrop")}</p>
            <p className="m-0 max-w-[460px] text-ui-xs leading-relaxed text-muted-foreground">{t("workflowImportDropHint")}</p>
            <Button variant="outline" size="sm" disabled={reading} onClick={() => fileRef.current?.click()}>
              {t("workflowImportPick")}
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept={WORKFLOW_IMPORT_ACCEPT}
              hidden
              onChange={(event) => {
                const picked = event.target.files?.[0];
                event.target.value = "";
                if (picked) void takeFile(picked);
              }}
            />
          </div>
          <div className="grid gap-1.5">
            <label htmlFor={textId} className="text-ui-xs font-medium text-muted-foreground">{t("workflowImportPasteLabel")}</label>
            <Textarea
              id={textId}
              aria-label={t("workflowImportPasteLabel")}
              rows={5}
              value={text}
              placeholder={t("workflowImportPastePlaceholder")}
              className="font-mono text-ui-xs"
              onChange={(event) => setText(event.target.value)}
              onPaste={(event) => {
                // 粘的是一张图(从别处复制的 ComfyUI 出图):按文件认
                const pasted = event.clipboardData?.files?.[0];
                if (pasted) {
                  event.preventDefault();
                  void takeFile(pasted);
                }
              }}
            />
          </div>
          {reading && <p role="status" className="m-0 text-ui-sm text-muted-foreground">{t("workflowImportReading")}</p>}
          {error && <p role="alert" className="m-0 whitespace-pre-line text-ui-sm text-destructive">{error}</p>}
        </div>
      )}
    </ModalShell>
  );
}
