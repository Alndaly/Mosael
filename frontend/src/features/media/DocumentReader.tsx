/**
 * 素材详情里的文档(ADR 0031):**左边解析出的全文,右边原版的每一页**(页面图),元信息在详情的最右栏。
 *
 * - 导入时后端已经用本地解析解过一遍;这里读**最新成功的那份**,上面写着是谁解析的、有什么提醒(扫描件、表格截断、
 *   装了 LibreOffice 能看到版式……)。点一段的标题,原版那一栏滚到那一页。
 * - 没有页面图的(Word / PPT 没装 LibreOffice、Excel、Markdown)只有全文一栏。
 * - 「重新解析」列出能用的几家(本地解析 + 配好了的插件,和「设置 → 能力提供方」同一张表);「存成笔记」把全文建成一篇笔记。
 * - 在解析就说在解析(每 1.5 秒看一次);失败了说原因、能重来。
 */
import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileText, Loader2, NotebookPen, RefreshCw, Square } from "lucide-react";
import { toast } from "sonner";

import { listCapabilityChoices } from "@/api/domains/capabilities";
import { capabilityKeys } from "@/api/queryKeys";
import { cancelJob } from "@/api/domains/jobs";
import { extractionFileUrl, extractionSections, listExtractions, parseDocument, type AssetExtraction } from "@/api/domains/documents";
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { AgentMarkdown } from "@/components/markdown/Markdown";
import { ActionMenu } from "@/components/app/ActionMenu";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { useSaveDocumentAsNote } from "@/features/media/useSaveDocumentAsNote";
import { cn } from "@/lib/utils";

const UNIT_LABEL: Record<string, MessageKey> = {
  page: "docUnitPage",
  slide: "docUnitSlide",
  sheet: "docUnitSheet",
  section: "docUnitSection",
};

/** 解析结果上的提醒(后端 local.Parsed.notes 的几种)。认不出的不显示 —— 不把一个键原样摆给人看。 */
const NOTES: Record<string, MessageKey> = {
  docNote_littleText: "docNote_littleText",
  docNote_pageImagesCapped: "docNote_pageImagesCapped",
  docNote_noPageImages: "docNote_noPageImages",
  docNote_tableTruncated: "docNote_tableTruncated",
};

/** 挂在 `asset` 底下:解析任务做完时,任务中心按「改动了素材」失效的键里有它(见 jobKinds 的 RESOURCE_QUERY_KEYS)。 */
export const extractionsKey = (assetId: string) => ["asset", assetId, "extractions"] as const;

/** Markdown 里的插图地址是相对解析目录的(`images/…`):换成带令牌的文件地址,`<img>` 才取得到。 */
export function withFileUrls(markdown: string, assetId: string, extractionId: string): string {
  return markdown.replace(/\]\(((?:images|pages)\/[^)\s]+)\)/g, (_all, path: string) => `](${extractionFileUrl(assetId, extractionId, path)})`);
}

export function DocumentReader({ assetId }: { assetId: string }) {
  const t = useI18n();
  const qc = useQueryClient();
  const extractions = useQuery({
    queryKey: extractionsKey(assetId),
    queryFn: () => listExtractions(assetId),
    refetchInterval: (query) => ((query.state.data ?? []).some((one) => one.status === "queued" || one.status === "running") ? 1500 : false),
  });
  const list = extractions.data ?? [];
  const latest = list[0];
  const done = list.find((one) => one.status === "succeeded");
  const busy = latest && (latest.status === "queued" || latest.status === "running");

  const parse = useMutation({
    mutationFn: (providerId: string | null) => parseDocument(assetId, providerId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: extractionsKey(assetId) }),
    onError: (error) => toast.error(errorText(error)),
  });
  const saveNote = useSaveDocumentAsNote();
  //: 一份几百页的 PDF 能解析好几分钟:开始了就得能停(此前只能等它跑完)。停的是那一次解析任务。
  const stop = useMutation({
    mutationFn: (jobId: string) => cancelJob(jobId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: extractionsKey(assetId) }),
    onError: (error) => toast.error(errorText(error)),
  });
  const stopped = latest?.status === "cancelled" && !done ? latest : undefined;

  return (
    <div data-document-reader="" className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)]">
      <header className="flex min-w-0 flex-wrap items-center gap-2 border-b border-divider px-4 py-2 text-ui-xs text-muted-foreground">
        {busy ? (
          <span className="inline-flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-primary"><Loader2 size={12} className="animate-spin" />{t("docParsing").replace("{parser}", latest.parser_name)}</span>
            {latest.job_id ? (
              <Button size="xs" variant="ghost" data-document-stop="" className="gap-1 px-2 text-ui-xs" loading={stop.isPending}
                      onClick={() => stop.mutate(latest.job_id!)}>
                <Square size={10} className="fill-current" />
                {t("docStopParse")}
              </Button>
            ) : null}
          </span>
        ) : stopped ? (
          <span data-document-stopped="">{t("docParseStopped").replace("{parser}", stopped.parser_name)}</span>
        ) : done ? (
          <span data-document-parsed-by="">
            {t("docParsedBy").replace("{parser}", done.parser_name).replace("{count}", String(done.sections)).replace("{unit}", t(UNIT_LABEL[done.unit] ?? "docUnitSection"))}
          </span>
        ) : null}
        <span className="flex-1" />
        <Button size="xs" variant="ghost" className="gap-1.5 px-2 text-ui-xs" disabled={!done} loading={saveNote.isPending}
                onClick={() => saveNote.mutate(assetId)}>
          <NotebookPen size={12} />
          {t("docSaveAsNote")}
        </Button>
        <ReparseMenu disabled={Boolean(busy) || parse.isPending} onPick={(providerId) => parse.mutate(providerId)} />
      </header>
      {done ? (
        <ParsedBody assetId={assetId} extraction={done} failed={latest?.status === "failed" && !busy ? latest : undefined} />
      ) : (
        <div className="min-h-0 overflow-y-auto px-5 py-4">
          {latest?.status === "failed" && !busy && <Failed extraction={latest} />}
          {!busy && (!latest || stopped) && (
            <div className="grid h-full place-items-center text-center text-muted-foreground">
              <span className="grid justify-items-center gap-2">
                <FileText size={32} strokeWidth={1.3} />
                <span className="max-w-[28rem] text-ui-xs leading-relaxed">{t("assetDocumentNotParsed")}</span>
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Failed({ extraction }: { extraction: AssetExtraction }) {
  const t = useI18n();
  return (
    <p role="alert" data-document-failed="" className="m-0 mb-3 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-ui-xs leading-relaxed text-destructive">
      <AlertTriangle size={13} className="mt-0.5 shrink-0" />
      <span className="min-w-0 [overflow-wrap:anywhere]">{t("docParseFailed").replace("{parser}", extraction.parser_name)} {extraction.error}</span>
    </p>
  );
}

function ParsedBody({ assetId, extraction, failed }: { assetId: string; extraction: AssetExtraction; failed?: AssetExtraction }) {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  const sections = useQuery({
    queryKey: [...extractionsKey(assetId), extraction.id, "sections"],
    queryFn: () => extractionSections(assetId, extraction.id),
  });
  const unit = t(UNIT_LABEL[extraction.unit] ?? "docUnitSection");
  const notes = (extraction.notes ?? []).flatMap((note) => (NOTES[note] ? [NOTES[note]] : []));
  const pages = extraction.page_images ?? [];
  const pagesRef = React.useRef<HTMLDivElement | null>(null);
  //: 点一段的标题,原版那一栏滚到那一页(PDF / PPT 的段就是页)。
  const showPage = (image: string | null | undefined) => {
    if (!image) return;
    pagesRef.current?.querySelector<HTMLElement>(`[data-document-page="${CSS.escape(image)}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <div className={cn("grid min-h-0", pages.length ? "grid-cols-[minmax(0,1fr)] md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" : "grid-cols-[minmax(0,1fr)]")}>
      <div data-document-text="" className="min-h-0 min-w-0 overflow-y-auto px-5 py-4">
        {failed && <Failed extraction={failed} />}
        {notes.length > 0 && (
          <ul data-document-notes="" className="m-0 mb-4 grid list-none gap-1 p-0 text-ui-xs leading-relaxed text-muted-foreground">
            {notes.map((note) => <li key={note}>· {t(note)}</li>)}
          </ul>
        )}
        <div className="grid gap-5">
          {(sections.data?.sections ?? []).map((section) => (
            <section key={section.index} data-document-section={section.index} className="grid min-w-0 gap-2 border-b border-divider pb-5 last:border-b-0">
              <h3 className="m-0 flex min-w-0 items-baseline gap-2 text-ui-xs font-medium text-muted-foreground">
                <button
                  type="button"
                  disabled={!section.image}
                  onClick={() => showPage(section.image)}
                  className="shrink-0 cursor-pointer border-0 bg-transparent p-0 tabular-nums text-inherit hover:text-foreground disabled:cursor-default disabled:hover:text-inherit"
                >
                  {t("docSectionLabel").replace("{unit}", unit).replace("{index}", String(section.index))}
                </button>
                {section.title && <Truncate className="text-foreground">{section.title}</Truncate>}
              </h3>
              <div className="min-w-0 text-ui-sm [overflow-wrap:anywhere]">
                <AgentMarkdown fullTables>{withFileUrls(section.markdown ?? "", assetId, extraction.id)}</AgentMarkdown>
              </div>
            </section>
          ))}
        </div>
      </div>
      {pages.length > 0 && (
        //: 原版:每一页的页面图,和解析出的文字对照着看。
        <div ref={pagesRef} data-document-pages="" className="min-h-0 min-w-0 overflow-y-auto border-l border-divider bg-workspace-subtle px-4 py-4">
          <div className="grid gap-4">
            {pages.map((image, index) => (
              <figure key={image} data-document-page={image} className="m-0 grid gap-1.5">
                <figcaption className="text-ui-2xs tabular-nums text-muted-foreground">{t("docSectionLabel").replace("{unit}", t("docUnitPage")).replace("{index}", String(index + 1))}</figcaption>
                <IconButton
                  unstyled
                  type="button"
                  className="block w-full cursor-zoom-in overflow-hidden rounded-md border border-border bg-white p-0 shadow-sm"
                  label={t("docSectionLabel").replace("{unit}", t("docUnitPage")).replace("{index}", String(index + 1))}
                  hint={t("assetClickToZoom")}
                  onClick={() => openImagePreview({ src: extractionFileUrl(assetId, extraction.id, image), title: `${index + 1}` })}
                >
                  <img src={extractionFileUrl(assetId, extraction.id, image)} alt="" loading="lazy" className="block h-auto w-full" />
                </IconButton>
              </figure>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** 「重新解析」:本地解析 + 配好了的插件,和「设置 → 能力提供方」同一张表。 */
function ReparseMenu({ disabled, onPick }: { disabled: boolean; onPick: (providerId: string | null) => void }) {
  const t = useI18n();
  const choices = useQuery({ queryKey: capabilityKeys.choices(), queryFn: listCapabilityChoices });
  const options = (choices.data ?? []).find((one) => one.capability === "document_parse")?.options ?? [];
  const ready = options.filter((option) => (option.missing ?? []).length === 0);
  return (
    <ActionMenu
      label={t("docReparse")}
      trigger={
        <Button size="xs" variant="ghost" disabled={disabled} aria-label={t("docReparse")} aria-haspopup="menu" className="gap-1.5 px-2 text-ui-xs">
          <RefreshCw size={12} />
          {t("docReparse")}
        </Button>
      }
      actions={ready.map((option) => ({
        label: t("docReparseWith").replace("{parser}", option.name),
        icon: <FileText size={14} />,
        onSelect: () => onPick(option.id),
      }))}
    />
  );
}
